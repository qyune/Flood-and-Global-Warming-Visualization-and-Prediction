import pandas as pd
import numpy as np
import boto3
import json
import sys
import re
from pyspark.sql import SparkSession, functions, types, Row
from sqlalchemy import create_engine
import country_converter as coco
import pycountry_convert as pc

assert sys.version_info >= (3, 5)  # make sure we have Python 3.5+

observation_schema = types.StructType([
    types.StructField('Year', types.TimestampType(), False),
    types.StructField('AverageTemperature', types.FloatType(), False),
    types.StructField('Country', types.StringType(), False),
    types.StructField('Country_Code', types.StringType(), False),

])


@functions.udf(returnType=types.StringType())
def country_convert(country):
    """Converting a country name to country code (ISO-3)"""
    cc = coco.CountryConverter(only_UNmember=True)
    return cc.convert(names=country, to='iso3')


@functions.udf(returnType=types.StringType())
def country_convert_to_iso2(code):
    """Converting a country code(ISO-3) to a country code (ISO-2)"""
    return coco.convert(names=code, to='iso2')


@functions.udf(returnType=types.StringType())
def country_convert_to_continent(code):
    """map a country code(ISO-2) to continent (ISO-2)"""
    return pc.country_alpha2_to_continent_code(code)


# Connecting to AWS RDS (Postgresql Engine) - output
engine = create_engine(
    'postgresql+psycopg2://postgres:Aws_2020@database-1.cwfbooless1u.us-east-1.rds.amazonaws.com:5432/postgres')


def main():
    # Reads input source from AWS S3 bucket
    temperature_df = spark.read.format('csv').options(header='true', schema='observation_schema') \
        .option("mode", "DROPMALFORMED").load(
        "s3://climate-data-732/AverageTemperatureByCountryYear.csv/part-00000-6aae2693-38c5-446e-a7bd-07a22581336e-c000.csv")
    # .option("mode", "DROPMALFORMED").load("part-00000-e53fb5db-78a6-4002-93d3-959312cbba25-c000.csv")
    temperature_df.cache()

    avg_temp_df_world = temperature_df.groupBy('Year').agg(
        functions.avg('AverageTemperature').alias('Avg_Temp_World')).orderBy('Year')
    avg_temp_df_world = avg_temp_df_world.withColumn('Avg_Temp_World',
                                                     functions.round(avg_temp_df_world['Avg_Temp_World'], 2))

    # # Save to DB P2-2
    avg_temp_df_world.toPandas().to_sql('graph_2_2', engine, if_exists='replace')

    avg_temp_df = temperature_df.groupBy('Year', 'Country').agg(
        functions.avg('AverageTemperature').alias('Avg_Temp'))

    avg_temp_df.select(functions.countDistinct("Country"))

    avg_temp_df.createOrReplaceTempView("avg_temp_view")

    avg_temp_df_85 = spark.sql("SELECT * "
                               "FROM  avg_temp_view "
                               "WHERE YEAR = 1985")
    avg_temp_df_85.createOrReplaceTempView("avg_temp_85_view")

    avg_temp_df_19 = spark.sql("SELECT * "
                               "FROM  avg_temp_view "
                               "WHERE YEAR = 2019")
    avg_temp_df_19.createOrReplaceTempView("avg_temp_19_view")

    joined_df = spark.sql("SELECT y1.Country, "
                          "y1.Year AS Year_85, y2.Year AS Year_19, "
                          "y1.Avg_Temp AS Avg_85, y2.Avg_Temp AS Avg_19 "
                          "FROM avg_temp_85_view y1 "
                          "JOIN avg_temp_19_view y2 "
                          "ON y1.Country = y2.Country")

    diff_df = joined_df.withColumn('Diff', (joined_df['Avg_19'] - joined_df['Avg_85']))

    # Adding country code column
    code_df = diff_df.withColumn('Code', country_convert(diff_df['Country']))
    code_df = code_df.filter(code_df['Code'] != 'not found')

    code_df = code_df.withColumn('Code2', country_convert_to_iso2(code_df['Code']))
    code_df = code_df.withColumn('Continent', country_convert_to_continent(code_df['Code2']))

    # adjust floating point precision to 2
    res_df = code_df.withColumn('Avg_85', functions.round(code_df['Avg_85'], 2))
    res_df = res_df.withColumn('Avg_19', functions.round(code_df['Avg_19'], 2))
    res_df = res_df.withColumn('Diff', functions.round(code_df['Diff'], 2))

    # Save to DB P2-1
    res_df.toPandas().to_sql('graph_2_1', engine, if_exists='replace')

    rank_df = res_df.orderBy('Diff', ascending=False)

    # Save to DB P2-3
    rank_df.toPandas().to_sql('graph_2_3', engine, if_exists='replace')


if __name__ == '__main__':
    spark = SparkSession.builder.appName('Worlds Temperature_GHCN').getOrCreate()
    assert spark.version >= '2.4'  # make sure we have Spark 2.4+
    spark.sparkContext.setLogLevel('WARN')
    sc = spark.sparkContext
    main()
