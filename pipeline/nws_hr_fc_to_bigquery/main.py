import os
import json

import geojson
from google.cloud import bigquery
from google.cloud import storage

dir_path = os.path.dirname(os.path.realpath(__file__))
os.chdir(dir_path)
DATASET_ID = 'raw_data'
TABLE_ID = 'nws_hourly_forecast'
PROJECT_ID = 'weather-forecast-accuracy'
storage_client = storage.Client()
bq_client = bigquery.Client()

def load_geojson_to_bq(request):
    """Responds to any HTTP request.
    Args:
        request (flask.Request): HTTP request object.
    Returns:
        The response text or any set of values that can be turned into a
        Response object using
        `make_response <http://flask.pocoo.org/docs/1.0/api/#flask.Flask.make_response>`.
    """
    dataset_ref = bq_client.dataset(DATASET_ID) # dataset_id here
    job_config = bigquery.LoadJobConfig()
    job_config.write_disposition = 'WRITE_APPEND'
    job_config.schema = bq_client.schema_from_json(r'schema.json')

    # get blobs from the directory excluding subdirectories and their files
    bucket_name = 'weather-forecasts-for-eval'
    bucket = storage_client.bucket(bucket_name)
    blobs = list(storage_client.list_blobs(bucket_name, prefix='nws/hourly/', delimiter='/'))
    # weather-forecasts-for-eval/kma/test_us
    # parse JSON file 
    json_rows = []
    invalid_files = []
    for blob in blobs:
        try:
            d = json.loads(blob.download_as_string(client=None))
            row = d['properties']
            row['geometry'] = geojson.dumps(d['geometry'])
            json_rows.append(row)
        except BaseException as e:
            invalid_files.append((blob.name, repr(e)))
    
    print('Finished json parsing.')
    if invalid_files:
        print('Check errors for', invalid_files)
        print('Check files in .invalid/')

    # Moving invalid files to ./invalid
    rename_errors = []
    for invalid_file, _ in invalid_files:
        invalid_blob = bucket.blob(invalid_file)
        try:
            last_slash_idx = invalid_blob.name.rfind('/')
            new_name = invalid_blob.name[:last_slash_idx] + '/invalid' + invalid_blob.name[last_slash_idx:]
            bucket.rename_blob(invalid_blob, new_name)
        except:
            rename_errors.append(invalid_blob.name)
            continue

    # load the data into BQ
    print('Loading data to BQ..')
    load_job = bq_client.load_table_from_json(
            json_rows=json_rows,#: Iterable[Dict[str, Any]]
            destination=dataset_ref.table(TABLE_ID),
            project=PROJECT_ID,
            job_config=job_config)

    load_job.result()  # wait for table load to complete.
    print('Load job finished.')

    # move files to '/done'
    bucket = storage_client.bucket(bucket_name)
    print('moving blobs to ./done')
    for blob in blobs:
        try:
            last_slash_idx = blob.name.rfind('/')
            new_name = blob.name[:last_slash_idx] + '/done' + blob.name[last_slash_idx:]
            bucket.rename_blob(blob, new_name)
        except:
            rename_errors.append(blob.name)
            continue
    
    print("Blob migration finished.")
    if rename_errors:
        print('Check migration errors for', rename_errors)

    return 'Job finished.'
    

if __name__ == '__main__':
    load_geojson_to_bq(None)