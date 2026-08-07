from services.mapfetcher import get_residential_map

print(" Starting map generator...")

# Replace these with the actual Lat/Lon of the house/neighborhood you want!
# (These coordinates are near Nishinosho, from your reference image)
get_residential_map(
    lat=34.2625,        
    lon=135.1430,       
    radius_meters=350,  
    output_filename="data/residential_map.png"
)

print("🎉 All done!")