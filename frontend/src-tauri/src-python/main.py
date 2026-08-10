from pathlib import Path
import json
from services.gpsparser import convert_gps_file, clean_gps_data, export_to_frontend_json

def data_pipeline_process(
    input_file: str,
    output_format: str = "iblue747",
) -> str:
    print(f"🔄 Processing file: {input_file}")

    # 1. Load the route from the GPS file
    route = convert_gps_file(input_file=input_file, output_filename=input_file.replace(".TXT", ".csv"), output_format=output_format)

    # 2. Cleaning and processing the route data
    cleaned_route = clean_gps_data(route) 

    # 3. Convert the data to JSON format for visualization
    json_route = export_to_frontend_json(cleaned_route, original_input_path=input_file, project_name="Untitled Project")

    print(f"✅ Pipeline completed successfully!")
    # Return as a serialized JSON string for the frontend
    return json.dumps(json_route, ensure_ascii=False)

if __name__ == "__main__":
    # Construct path using pathlib concatenation
    base_file_path = Path(__file__).resolve().parent / "data" / "inputs" / "gpsdata" / "rawdata" 
    input_file_path = base_file_path / "LOG00002.TXT"

    # Verify path existence before running
    if input_file_path.exists():
        data_pipeline_process(str(input_file_path), output_format="iblue747")
    else:
        print(f"❌ Error: The file does not exist at path: {input_file_path.absolute()}")
        print(f"Please check if 'LOG00002.TXT' is placed inside: {base_file_path.absolute()}")