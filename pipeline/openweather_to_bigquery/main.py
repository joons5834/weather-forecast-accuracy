import os
import json

from google.cloud import bigquery
from google.cloud import storage

dir_path = os.path.dirname(os.path.realpath(__file__))
os.chdir(dir_path)
DATASET_ID = os.getenv('DATASET_ID')# 'raw_data'
TABLE_ID = os.getenv('TABLE_ID')# 'openweathermap_h_d'
PROJECT_ID = os.getenv('PROJECT_ID')# 'weather-forecast-accuracy'
storage_client = storage.Client()
bq_client = bigquery.Client()

def load_openweather_to_bq(request):
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
    job_config.schema = bq_client.schema_from_json(r'owm_schema.json')
    job_config.clustering_fields = ['current_dt']

    # get blobs from the directory excluding subdirectories and their files
    bucket_name = os.getenv('BUCKET_NAME') #'openweather-api-data'
    bucket = storage_client.bucket(bucket_name)
    blobs = list(storage_client.list_blobs(bucket_name, delimiter='/'))
    json_rows = []
    invalid_files = []
    for blob in blobs:
        try:
            d = json.loads(blob.download_as_string(client=None))

            # change invalid column name '1h' to 'last_hr'
            last_hours = [d['current']] + d['hourly']
            weathers = ['rain', 'snow']
            for last_hour in last_hours:
                for weather in weathers:
                    if weather in last_hour and '1h' in last_hour[weather]:
                        print('before:',last_hour)
                        last_hour[weather]['last_hr'] = last_hour[weather]['1h'] 
                        del last_hour[weather]['1h']
                        print('after:', last_hour)

            # Move dict `current` to the root level for the cluster/partition column(s)
            for key in d['current']:
                d['current_' + key] = d['current'][key]
            del d['current']

            json_rows.append(d)
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
            if last_slash_idx != -1:
                new_name = invalid_blob.name[:last_slash_idx] + '/invalid' + invalid_blob.name[last_slash_idx:]
            else:
                new_name = 'invalid/' + invalid_blob.name
            bucket.rename_blob(invalid_blob, new_name)
        except:
            rename_errors.append(invalid_blob.name)
            continue

    # load the data into BQ
    if not json_rows:
        print('Zero rows to load. Job finished')
        return 'Zero rows to load. Job finished'
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
            if last_slash_idx != -1:
                new_name = blob.name[:last_slash_idx] + '/done' + blob.name[last_slash_idx:]
            else:
                new_name = 'done/' + blob.name
            bucket.rename_blob(blob, new_name)
        except:
            rename_errors.append(blob.name)
            continue
    
    print("Blob migration finished.")
    if rename_errors:
        print('Check migration errors for', rename_errors)

    return 'Job finished.'
    

if __name__ == '__main__':
    load_openweather_to_bq(None)