# Garmin Devices Scraper

This project scrapes and maintains a structured list of Garmin Connect IQ compatible devices, including their technical details and API levels. It fetches data from the official Garmin developer website, tracks new and deprecated devices, and outputs the results as both JSON and Markdown tables.

## Features

- **Automatic scraping** of Garmin device reference and API level pages.
- **Parallel fetching** for fast updates of new device details.
- **Tracks deprecated devices** and marks them as inactive.
- **Outputs**:
  - `garmin_devices.json`: Full device data in JSON format.
  - `garmin_devices.md`: Human-readable Markdown table of devices.

## Usage

1. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

2. **Run the script**:

   ```bash
   python parse.py
   ```

3. **View outputs**:
   - `garmin_devices.json`: Structured device data for querying.
   - `garmin_devices.md`: Markdown table for easy overview.

## How it Works

- Checks for and loads any existing device data from `garmin_devices.json`.
- Scrapes the [Garmin Connect IQ Device Reference](https://developer.garmin.com/connect-iq/device-reference/) for the current device list.
- Fetches details for new devices and marks missing ones as deprecated.
- Enriches device data with API levels from the [Compatible Devices](https://developer.garmin.com/connect-iq/compatible-devices/) page.
- Saves updated data to JSON and Markdown files.

## License

This project is provided for educational and research purposes. It is not affiliated with or endorsed by Garmin.
