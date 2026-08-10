import sys
import json
from pathlib import Path
from services.gpsparser import convert_gps_file, clean_gps_data, export_to_frontend_json
from services.filehandler import store_raw_file_with_datetime

def data_pipeline_process(input_file: str, output_format: str = "iblue747") -> str:
    print(f"🔄 Processing file: {input_file}")
    route = convert_gps_file(input_file=input_file, output_filename=input_file.replace(".TXT", ".csv"), output_format=output_format)
    cleaned_route = clean_gps_data(route) 
    json_route = export_to_frontend_json(cleaned_route, original_input_path=input_file, project_name="Untitled Project")
    print(f"✅ Pipeline completed successfully!")
    return json.dumps(json_route, ensure_ascii=False)

def store_raw_file(input_file: str) -> str:
    stored_file_path = store_raw_file_with_datetime(input_file)
    if stored_file_path:
        print(f"Raw file stored at: {stored_file_path}")
    else:
        print("Failed to store raw file.")
    return stored_file_path

def handle_incoming_gps_upload(raw_source_path: str) -> str:
    stored_path = store_raw_file(raw_source_path)
    if not stored_path:
        raise ValueError(f"Failed to store raw file from: {raw_source_path}")
    return data_pipeline_process(input_file=stored_path, output_format="iblue747")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        payload = sys.argv[2] if len(sys.argv) > 2 else ""

        try:
            if command == "process_gps":
                result_json = handle_incoming_gps_upload(payload)
                print(result_json)
            else:
                print(f"Error: Unknown command '{command}'", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"Error: {str(e)}", file=sys.stderr)
            sys.exit(1)