import re
import os
import json
import requests
import concurrent.futures
from bs4 import BeautifulSoup
from tqdm import tqdm

# --- Configuration ---
BASE_URL = "https://developer.garmin.com"
INDEX_URL = f"{BASE_URL}/connect-iq/device-reference/"
API_LVL_URL = f"{BASE_URL}/connect-iq/compatible-devices/"
DETAIL_URL_TEMPLATE = f"{BASE_URL}/connect-iq/articles/device-reference/{{device_id}}.html"
JSON_FILENAME = "garmin_devices.json"
MD_FILENAME = "garmin_devices.md"
MAX_WORKERS = 10 # Number of parallel threads to fetch device details


def load_from_json(filename: str) -> dict:
    """
    Loads device data from a JSON file if it exists.
    Returns a dictionary of devices keyed by their 'Id'.
    """
    if not os.path.exists(filename):
        print(f"'{filename}' not found. Will fetch all device data from scratch.")
        return {}
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data_list = json.load(f)
            # Convert list of dicts to a dict keyed by device 'Id' for efficient lookups
            return {device.get('Id', ''): device for device in data_list if device.get('Id')}
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error reading or parsing '{filename}': {e}. Starting fresh.")
        return {}


def save_to_json(filename: str, data_dict: dict):
    """
    Saves the device data dictionary to a JSON file.
    The data is stored as a list of device objects, sorted by name.
    """
    # Convert the dictionary values back to a list for standard JSON array output
    data_list = sorted(list(data_dict.values()), key=lambda d: d.get('Name', ''))
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data_list, f, indent=4, ensure_ascii=False)
        print(f"\nSuccessfully saved updated data for {len(data_list)} devices to '{filename}'.")
    except IOError as e:
        print(f"Error saving data to '{filename}': {e}")


def get_device_ids() -> set:
    """
    Fetches the main device reference page and extracts all unique device IDs.
    Returns a set of device IDs for efficient comparison.
    """
    print(f"Fetching current device list from {INDEX_URL}...")
    try:
        response = requests.get(INDEX_URL)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"FATAL: Could not fetch index page: {e}. Aborting.")
        return set()

    soup = BeautifulSoup(response.content, 'html.parser')
    device_link_pattern = re.compile(r"^/connect-iq/device-reference/.+/$")
    device_links = soup.find_all('a', href=device_link_pattern)
    device_ids = {a['href'].strip('/').split('/')[-1].replace('-', '_') for a in device_links}
    
    print(f"Found {len(device_ids)} unique device IDs on the index page.")
    return device_ids


def parse_device_details(device_id: str) -> dict | None:
    """
    Fetches and parses the details page for a single device ID.
    Returns a dictionary of the device's properties or None on failure.
    """
    detail_url = DETAIL_URL_TEMPLATE.format(device_id=device_id)
    try:
        response = requests.get(detail_url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return None

    soup = BeautifulSoup(response.content, 'html.parser')
    article = soup.find('article', role='article')
    if not article: return None

    device_data = {'Active': True} # Default status for new/active devices
    h1 = article.find('h1')
    device_data['Name'] = h1.text.strip() if h1 else device_id

    tables = article.find_all('table')
    if len(tables) < 2: return None

    # Parse first table (Attributes)
    for row in tables[0].find('tbody').find_all('tr'):
        cells = row.find_all('td')
        if len(cells) == 2:
            col_id = cells[0].text.replace(" ", "")
            device_data[col_id] = cells[1].text.strip()
            if col_id == 'ScreenSize':
                # split into width and height
                size_parts = device_data[col_id].split('x')
                if len(size_parts) == 2:
                    device_data['ScreenWidth'] = size_parts[0].strip()
                    device_data['ScreenHeight'] = size_parts[1].strip()

    # Parse second table (App Types)
    for row in tables[1].find('tbody').find_all('tr'):
        cells = row.find_all('td')
        if len(cells) == 3:
            app_type, app_memory = cells[0].text.replace(" ", ""), cells[1].text.strip()
            device_data[f"{app_type}Memory"] = app_memory

    # Ensure the 'Id' key exists, which we use for our dictionary
    if 'Id' not in device_data:
        device_data['Id'] = device_id

    return device_data


def get_api_levels() -> dict[str, str]:
    """
    Fetches the 'Compatible Devices' page and parses all tables to create
    a map of { device_name: api_level }.
    """
    print(f"\nFetching API levels from {API_LVL_URL}...")
    
    try:
        response = requests.get(API_LVL_URL)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Warning: Could not fetch API levels page: {e}. Skipping this step.")
        return {}

    soup = BeautifulSoup(response.content, 'html.parser')
    api_level_map = {}
    
    tables = soup.find_all('table')
    if not tables:
        print("Warning: No tables found on the API levels page.")
        return {}

    for table in tables:
        # The data is in the table body
        tbody = table.find('tbody')
        if not tbody:
            continue # Skip if table has no body

        for row in tbody.find_all('tr'):
            cells = row.find_all('td')
            # We need at least two columns: Name and API Level (which is last)
            if len(cells) >= 2:
                # First column is the name, last column is the API level
                device_name = cells[0].text.strip()
                api_level = cells[-1].text.strip()
                
                if device_name and api_level:
                    api_level_map[device_name] = api_level

    print(f"Found API levels for {len(api_level_map)} device names.")
    return api_level_map


def enrich_with_api_levels(all_devices_data: dict) -> dict:
    """
    Enriches the main device data dictionary with API Level information.
    It maps the data using the device 'Name' field as the key.
    """
    # Get the mapping of { 'Device Name': 'API Level' }
    api_levels_by_name = get_api_levels()
    if not api_levels_by_name:
        return all_devices_data # Return original data if we couldn't get API levels

    # Create a reverse map from our existing data for efficient lookups:
    # { 'fēnix® 7': 'fenix7', ... }
    name_to_id_map = {
        device.get('Name'): device_id
        for device_id, device in all_devices_data.items() if device.get('Name')
    }

    update_count = 0
    # Iterate through the newly scraped API level data
    for device_name, api_level in api_levels_by_name.items():
        # Find the corresponding device_id using the device name
        device_id = name_to_id_map.get(device_name)
        
        # If we found a match, update that device's data in our main dictionary
        if device_id:
            all_devices_data[device_id]['APILevel'] = api_level
            update_count += 1
        else:
            print(f"No device reference found for '{device_name}'. Skipping.")
            
    print(f"Successfully mapped and added API levels to {update_count} devices.")
    return all_devices_data


def save_markdown_table(filename, all_devices_data: dict):
    """
    Prints a dictionary of device data as a formatted Markdown table.
    """
    if not all_devices_data:
        print("No device data to generate a table from.")
        return

    # Define headers, including the new 'Active' column
    headers = [
        'Active', 
        'Name', 
        'Id', 
        'ScreenShape',
        'ScreenSize',
        'Touch',
        'APILevel', 
        'WatchAppMemory',
        'WatchFaceMemory',
        'DataFieldMemory',
        'Buttons'
    ]

    # Sort by name for consistent output
    data_list = sorted(all_devices_data.values(), key=lambda d: d.get('Name', ''))

    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"| {' | '.join(headers)} |\n")
            f.write(f"|{'|'.join(['---'] * len(headers))}|\n")
            for device in data_list:
                row_data = [
                    str(device.get(h, 'N/A')).replace('|', '\\|') for h in headers
                ]
                f.write(f"| {' | '.join(row_data)} |\n")
        print(f"\nSuccessfully saved markdown table data for {len(data_list)} devices to '{filename}'.")
    except IOError as e:
        print(f"Error saving data to '{filename}': {e}")
    

def main():
    """
    Main function to orchestrate loading, diffing, scraping, and printing.
    """
    # 1. Load existing data from JSON
    existing_devices_data = load_from_json(JSON_FILENAME)
    existing_ids = set(existing_devices_data.keys())

    # 2. Get the current list of device IDs from the web
    current_device_ids = get_device_ids()
    if not current_device_ids:
        print("FATAL: Could not fetch the master list of devices. Aborting.")
        return # Exit if we couldn't fetch the master list

    # 3. Compare the lists to find what's new and what's been removed
    new_ids = current_device_ids - existing_ids
    deprecated_ids = existing_ids - current_device_ids
    
    # This keeps a reference to our main data object
    updated_devices_data = existing_devices_data

    # 4. Handle deprecated devices
    if deprecated_ids:
        print(f"\nMarking {len(deprecated_ids)} device(s) as Deprecated: {', '.join(deprecated_ids)}")
        for dev_id in deprecated_ids:
            if dev_id in updated_devices_data:
                updated_devices_data[dev_id]['Active'] = False

    # 5. Fetch new devices
    if new_ids:
        # 5.1. Fetch details for new devices in parallel
        print(f"\nFound {len(new_ids)} new device(s). Fetching details...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = list(tqdm(executor.map(parse_device_details, new_ids), total=len(new_ids), desc="Fetching new devices"))
        
        newly_parsed_count = 0
        for data in results:
            if data and 'Id' in data:
                updated_devices_data[data['Id']] = data
                newly_parsed_count += 1
        print(f"Successfully parsed details for {newly_parsed_count} new device(s).")
            
        # 5.2. Enrich data with API Levels
        updated_devices_data = enrich_with_api_levels(updated_devices_data)
    else:
        print("\nNo new devices found.")

    # 6. Save the consolidated data back to JSON
    if new_ids or deprecated_ids or active_again_ids:
        save_to_json(JSON_FILENAME, updated_devices_data)
    else:
        print("\nNo changes to local data file needed.")

    # 7. Save the final markdown table
    save_markdown_table(MD_FILENAME, updated_devices_data)

if __name__ == "__main__":
    main()