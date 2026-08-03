import json
from pathlib import Path
import requests
import numpy as np
import datetime
import pandas as pd
from erddapy import ERDDAP

if Path('../secrets.json').exists():
    with open('../secrets.json') as f:
        oceanops_auth = json.load(f)
headers = {
    'Content-Type': 'application/json' ,
    'accept': 'application/json' ,
    **oceanops_auth
}

non_standard_ends = {
    'SEA061_M63': 'hit-by-ship',
    'SEA078_M43': 'unknown',
}

def init_erddap():
    e = ERDDAP(
        server="https://erddap.observations.voiceoftheocean.org/erddap",
        protocol="tabledap",
    )
    e.response = "csv"
    return e

e = init_erddap()

def fetch_passports_from_wmo_id(wmo_id):

    wigos_ids = [f'0-22000-{num}-{wmo_id}' for num in range(1000)]
    oceanops_info = {}

    denied_count = 0
    for wigos_id in wigos_ids:
        _, _, passport_num, _ = wigos_id.split('-')
        url = f'https://www.ocean-ops.org/api/data/platforms/{wigos_id}'
        response = requests.patch(url, headers=headers, json={})
        if response.status_code == 403:
            print(f"Access denied! Check you are authorised for this wmo {wmo_id}. Wigos ID {wigos_id}")
            denied_count += 1
            if denied_count > 5:
                print(f"Access denied 5 times! Aborting for this wmo {wmo_id}.")
                return
            continue
        if response.status_code == 404:
            print(f"Maxed out at {wigos_id} which does not exist. Total existing wigos IDs = {passport_num}")
            break
        resp_json = response.json()
        oceanops_info[wigos_id] = resp_json
    oceanops_info_flat = {}
    for dataset_id, ddict in oceanops_info.items():
        _, _, passport_num, _ = ddict['wigosId'].split('-')
        flat_ddict = {'passport_num': int(passport_num)}
        for key, val in ddict.items():
            if type(val) != dict:
                flat_ddict[key] = val
                continue
            for sub_key, sub_val in val.items():
                flat_ddict[f'{key}_{sub_key}'] = str(sub_val)
        oceanops_info_flat[dataset_id] = flat_ddict
    df_oceanops = pd.DataFrame(oceanops_info_flat).T
    for date_field in ['deployment_date', 'retrieval_startDate', 'retrieval_endDate']:
        if date_field in list(df_oceanops):
            df_oceanops[date_field] = pd.to_datetime(df_oceanops[date_field])
    df_oceanops = df_oceanops.sort_values('deployment_date')
    return df_oceanops

def fetch_platform_meta(platform_serial):

    e.dataset_id = "allDatasets"
    df_datasets = e.to_pandas()
    df_datasets = df_datasets[df_datasets.datasetID.str.contains("OG_nrt")]
    df_ids = df_datasets.datasetID.str[7:].str.split('_', expand=True)
    df_datasets['platform_serial'] = df_ids[0]
    df_datasets['mission'] = df_ids[1].str[1:].astype(int)
    df_platform = df_datasets[df_datasets.platform_serial == platform_serial]
    df_platform = df_platform.rename({'minTime (UTC)': 'deployment_date', 'maxTime (UTC)': 'recovery_date'}, axis=1)
    vars = ['datasetID', 'title', 'summary', 'platform_serial', 'mission', 'deployment_date', 'recovery_date']
    df_platform['deployment_date'] = pd.to_datetime(df_platform.deployment_date)
    df_platform['recovery_date'] = pd.to_datetime(df_platform.recovery_date)
    df_platform = df_platform[vars]
    df_platform = df_platform.sort_values('deployment_date')
    df_platform['gtsId'] = 6801506
    print(f"Found data for {len(df_platform)} deployments on ERDDAP")
    return df_platform


def match_wmo_platform_meta(df_oceanops, df_platform):
    df_platform['wigosId'] = ''
    matches = 0
    for i, row in df_platform.iterrows():
        deploy_diff = df_oceanops.deployment_date - row.deployment_date
        time_match = np.abs(deploy_diff) < np.timedelta64(3, 'D')
        if time_match.any():
            matching_passports = df_oceanops[time_match]
            if len(matching_passports == 1):
                matches += 1
                df_platform.loc[i, 'wigosId'] = matching_passports['wigosId'].values[0]
            else:
                print("Error! More than one match detected")
    print(f'Matched {matches} datasets')

    datasets_no_wigos = df_platform[df_platform['wigosId'] == '']
    if not datasets_no_wigos.empty:
        print(f"Failed to find wigos IDs for these datasetson  ERDDAP:")
        print(datasets_no_wigos[['datasetID', 'deployment_date', 'recovery_date']])

    unmatched_wigos = set(df_oceanops.index).difference(set(df_platform.wigosId))
    if unmatched_wigos:
        print("No corresponding dataset found on ERDDAP for assigned wigos passports:")
        print(df_oceanops[df_oceanops.wigosId.isin(unmatched_wigos)][['deployment_date', 'retrieval_startDate']])
    dfa = df_platform[
        ['datasetID', 'mission', 'title', 'deployment_date', 'recovery_date', 'wigosId', 'gtsId', 'platform_serial']]
    dfa = dfa[dfa.wigosId!=''] # drop lines that do not have a wigos passport
    keeps = ['passport_num', 'wigosId', 'name', 'deployment_date', 'identification_internalId', 'retrieval_startDate',
         'retrieval_endDate', 'retrieval_endingCause']
    cols = list(set(keeps).intersection(list(df_oceanops)))
    dfb = df_oceanops[cols]
    df = pd.merge(dfa, dfb, left_on='wigosId', right_on='wigosId', suffixes=('_voto', '_ops'), how='left')
    return df

def write_goos_tables(df, output_dir):
    passport_file = output_dir / 'goos_passport.csv'
    sensor_file = output_dir /'goos_sensor.csv'
    if passport_file.exists():
        df_passport_old = pd.read_csv(passport_file, sep=';')
        existing_passport_ids = df_passport_old['PASSPORT IDENTIFIER'].values
    else:
        existing_passport_ids = []
    passport_dicts = []
    sensor_dicts = []
    for i, row in df.iterrows():
        e.dataset_id = row.datasetID
        model = 'seaexplorer- shallow' if 'SHW' in row.datasetID else 'seaexplorer'
        passport_id = row.wigosId
        if not passport_id or not row.datasetID:
            continue
        if passport_id in existing_passport_ids:
            continue
        print(f"adding data from {row.datasetID}")
        platform_serial = row.platform_serial
        mission_id = f"{platform_serial}_M{row.mission}"
        ds = e.to_xarray()
        attrs = ds.attrs
        passport_dict = {'PASSPORT IDENTIFIER': passport_id,
                         'PROGRAM': 'voto-ocean-knowledge-glider-program',
                         'PLATFORM MODEL': model,
                         'PLATFORM SERIAL NUMBER': platform_serial,
                         'DEPLOYMENT DATE': str(ds.time.values[~np.isnan(ds.time)][0])[:19] + 'Z',
                         'DEPLOYMENT LATITUDE': ds.latitude.values[~np.isnan(ds.latitude)][0],
                         'DEPLOYMENT LONGITUDE': ds.longitude.values[~np.isnan(ds.longitude)][0],
                         'DEPLOYMENT SHIP': 'OCEAN SEEKER',  # tbd
                         'GTS ID': int(attrs['wmo_id']),
                         'TELECOM TYPE': 'iridium',
                         }

        # conditional entries
        conditional_dict = {
            'PRINCIPAL INVESTIGATOR': 'Louise Biddle',
            'AGENCIES': 'voto',
            'AGENCY_ROLES': 'operating-agency',
            'CONTRIBUTORS': attrs['contributor_name'],
            'CONTRIBUTOR_ROLE': attrs['contributor_role']

        }
        end_time = ds.time.values[~np.isnan(ds.time)][-1]
        if mission_id in non_standard_ends.keys():
            ending_cause = non_standard_ends[mission_id]
        else:
            ending_cause = 'voluntary-recovery-of-the-platform'
        if end_time < np.datetime64(datetime.datetime.now() - datetime.timedelta(days=3)):
            passport_dict['END DATE'] = str(ds.time.values[~np.isnan(ds.time)][-1])[:19] + 'Z'
            passport_dict['ENDING CAUSE'] = ending_cause
        passport_dict = passport_dict | conditional_dict
        passport_dicts.append(passport_dict)

        from string import ascii_uppercase as auc
        i = 0
        for var_name in ds.variables:
            variable = ds[var_name]
            attrs = variable.attrs
            if 'sensor' not in attrs.keys():
                continue
            if attrs['sensor'][:6] != 'SENSOR':
                continue
            sensor_dict = ds[attrs['sensor']].attrs
            if 'ad2cp' in sensor_dict['sensor_model'].lower():
                continue
            if 'standard_name' not in attrs.keys():
                continue
            sensor_dict = {
                'PASSPORT IDENTIFIER': passport_id,
                'SHORTCODE': auc[i],
                'SENSOR MODEL': sensor_dict['sensor_model'],
                'VARIABLE': attrs['standard_name'],
                'SERIAL NUMBER': sensor_dict['sensor_serial_number'],
            }
            i += 1
            sensor_dicts.append(sensor_dict)
    if len(passport_dicts) == 0:
        print("No new info, no write")
        return
    df_passport = pd.DataFrame(passport_dicts)
    df_sensor = pd.DataFrame(sensor_dicts)
    if passport_file.exists():
        df_passport = pd.concat([pd.read_csv(passport_file, sep=';'), df_passport])
        df_sensor = pd.concat([pd.read_csv(sensor_file, sep=';'), df_sensor])
    df_passport.to_csv(passport_file, sep=';', index=False)
    df_sensor.to_csv(sensor_file, sep=';', index=False)


class Passports:
    def __init__(self):
        self.platform_wmo = {}
        self.df_passport = pd.DataFrame()
        self.df_oceanops= pd.DataFrame()
        self.output_dir = Path('.')
        self.passport_file = self.output_dir / 'passport_info.csv'

    def load_existing(self):
        if self.passport_file.exists():
            self.df_passport = pd.read_csv(self.passport_file)
            existing_serials = self.df_passport['platform_serial'].unique()
            to_fetch = {platform: wmo for platform, wmo in self.platform_wmo.items() if
                        platform not in existing_serials}
            self.platform_wmo = to_fetch
            print(f"skipping known wmos, fetching only {self.platform_wmo}")

    def fetch_passports(self):
        df = self.df_passport
        for platform_serial, wmo in self.platform_wmo.items():
            df_oceanops = fetch_passports_from_wmo_id(wmo)
            if df_oceanops.empty:
                continue
            df_platform = fetch_platform_meta(platform_serial)
            df_combined = match_wmo_platform_meta(df_oceanops, df_platform)
            df = pd.concat((df, df_combined))
        self.df_passport = df
        df.to_csv(self.passport_file, index=False)
    def write_tables(self):
        write_goos_tables(self.df_passport, output_dir=self.output_dir)

def main():
    passport = Passports()
    passport.platform_wmo = {
        'SEA044': 6801672,
        'SEA045': 6801673,
        'SEA055': 6801673,
        'SEA056': 6801675,
        'SEA061': 6801706,
        'SEA063': 6801707,
        'SEA066': 6801505,
        'SEA067': 6801507,
        'SEA068': 6801602,
        'SEA069': 6801506,
        'SEA076': 6801665,
        'SEA077': 8901050,
        'SEA078': 8901000,
        'SEA079': 8901001,
        'SHW001': 8901081,
        'SHW002': 8901183,
        'SHW003': 8901204,
    }
    passport.load_existing()
    passport.fetch_passports()
    passport.write_tables()

if __name__ == '__main__':
    main()