import streamlit as st
import requests
import os
from dotenv import load_dotenv
import json
import logging

# Load environment variables
load_dotenv()
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY")

# Configure logging
logging.basicConfig(level=logging.DEBUG)

class RouteOptimizer:
    def __init__(self):
        self.tomtom_api_key = TOMTOM_API_KEY
        self.openweathermap_api_key = "4c61f798e1507fb0f06b70da4c7d41c8"  # Replace with your key
        self.aqicn_api_key = "4a46023e39f843b14cad08e314749000b54be42c"  # Replace with your key

    def get_coordinates(self, place):
        url = f"https://api.tomtom.com/search/2/geocode/{place}.json"
        params = {"key": self.tomtom_api_key, "limit": 1}
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("results"):
                position = data["results"][0]["position"]
                return position["lat"], position["lon"]
            return None
        except requests.RequestException as e:
            logging.error(f"Geocoding error for {place}: {str(e)}")
            return None

    def get_routes(self, waypoints):
        if len(waypoints) < 2:
            raise ValueError("At least two waypoints are required")

        coords = [self.get_coordinates(wp) for wp in waypoints if self.get_coordinates(wp)]
        if len(coords) < 2:
            raise ValueError("Invalid waypoints: Could not geocode all addresses")

        locations = ":".join([f"{lat},{lon}" for lat, lon in coords])
        url = f"https://api.tomtom.com/routing/1/calculateRoute/{locations}/json"
        params = {
            "key": self.tomtom_api_key,
            "routeType": "fastest",
            "traffic": "true",
            "computeTravelTimeFor": "all",
            "travelMode": "car"
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if "routes" not in data:
                raise ValueError("No routes found in TomTom API response")
            return [self.parse_route(route) for route in data["routes"]]
        except requests.RequestException as e:
            logging.error(f"Routing API error: {str(e)} - Response: {response.text}")
            error_data = response.json() if response.text else {}
            raise ValueError(f"Routing request failed: {error_data.get('detailedError', {}).get('message', str(e))}") from e

    def parse_route(self, route):
        return {
            "distance": route["summary"]["lengthInMeters"],
            "duration": route["summary"]["travelTimeInSeconds"],
            "polyline": route["legs"][0]["points"],
            "summary": route["summary"]
        }

    def compare_routes(self, routes):
        def heuristic(route):
            return route["duration"] + route["distance"] / 100

        scored_routes = [(route, heuristic(route)) for route in routes]
        best_route = min(scored_routes, key=lambda x: x[1])
        return {"best_route": best_route[0], "other_routes": []}

    def get_weather_data(self, location):
        url = f"https://api.openweathermap.org/data/2.5/weather"
        params = {
            "lat": location[0],
            "lon": location[1],
            "appid": self.openweathermap_api_key,
            "units": "metric"
        }
        try:
            response = requests.get(url, params=params)
            data = response.json()
            return {
                "temperature": data["main"]["temp"],
                "humidity": data["main"]["humidity"],
                "wind_speed": data["wind"]["speed"],
                "precipitation": data.get("rain", {}).get("1h", 0)
            }
        except Exception as e:
            logging.error(f"Weather API error: {str(e)}")
            return None

    def get_air_quality(self, location):
        url = f"https://api.waqi.info/feed/geo:{location[0]};{location[1]}/"
        params = {"token": self.aqicn_api_key}
        try:
            response = requests.get(url, params=params)
            data = response.json()
            return data["data"]["aqi"]
        except Exception as e:
            logging.error(f"Air Quality API error: {str(e)}")
            return None

    def get_traffic_flow(self, lat, lon):
        url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json"
        params = {"key": self.tomtom_api_key, "point": f"{lat},{lon}"}
        try:
            response = requests.get(url, params=params)
            data = response.json()
            return data.get("flowSegmentData", {})
        except Exception as e:
            logging.error(f"Traffic Flow API error: {str(e)}")
            return None

    def calculate_emissions(self, route, vehicle_type, package_weight):
        base_emission_rate = {
            "car": 120,
            "truck": 300,
            "van": 200,
            "bike": 0,
            "flying": 250,
            "public-transport": 50,
        }
        distance_km = route["distance"] / 1000
        base_emissions = base_emission_rate.get(vehicle_type, 150) * distance_km
        weight_factor = 1 + (package_weight * 0.01)
        return base_emissions * weight_factor

    def get_route(self, waypoints, vehicle_type, package_weight):
        routes = self.get_routes(waypoints)
        compared_routes = self.compare_routes(routes)
        best_route = compared_routes["best_route"]

        start_coords = self.get_coordinates(waypoints[0])
        weather_data = self.get_weather_data(start_coords) if start_coords else None
        air_quality = self.get_air_quality(start_coords) if start_coords else None
        traffic_flow = self.get_traffic_flow(start_coords[0], start_coords[1]) if start_coords else None

        best_route_emissions = self.calculate_emissions(best_route, vehicle_type, package_weight)
        return {
            "route": compared_routes,
            "emissions": best_route_emissions,
            "weather": weather_data,
            "air_quality": air_quality,
            "traffic_flow": traffic_flow
        }

# Streamlit UI
def main():
    st.title("Smart Route Optimizer")

    optimizer = RouteOptimizer()

    # Waypoints Input
    st.subheader("Waypoints")
    waypoints = []
    num_waypoints = st.number_input("Number of Waypoints", min_value=2, max_value=7, value=2, step=1)
    for i in range(num_waypoints):
        waypoint = st.text_input(f"Waypoint {i+1}", f"Delhi" if i == 0 else f"Mumbai" if i == 1 else f"Location {i+1}")
        waypoints.append(waypoint)

    # Vehicle Type and Package Weight
    vehicle_type = st.selectbox(
        "Vehicle Type",
        ["car", "truck", "van", "bike", "flying", "public-transport"],
        index=0
    )
    package_weight = st.number_input("Package Weight (kg)", min_value=0.0, value=0.0, step=0.1)

    # Geopolitical View
    geopol_view = st.selectbox("Geopolitical View", ["Unified", "IN", "IL", "MA", "PK", "AR", "TR", "CN"], index=1)

    if st.button("Optimize Route"):
        try:
            with st.spinner("Optimizing route..."):
                result = optimizer.get_route(waypoints, vehicle_type, package_weight)

            # Best Route Display
            st.subheader("Best Route")
            best_route = result["route"]["best_route"]
            st.write(f"Distance: {(best_route['distance'] / 1000):.2f} km")
            st.write(f"Duration: {(best_route['duration'] / 60):.2f} minutes")
            st.write(f"Emissions: {result['emissions']:.2f} g CO2")
            if result["weather"]:
                st.write(f"Weather: {result['weather']['temperature']}°C, Wind: {result['weather']['wind_speed']} km/h, Humidity: {result['weather']['humidity']}%")
            if result["air_quality"]:
                st.write(f"Air Quality Index: {result['air_quality']}")
            if result["traffic_flow"]:
                st.write(f"Traffic Flow - Avg Speed: {result['traffic_flow'].get('currentSpeed', 'N/A')} km/h")

            # Route Summary
            summary = best_route["summary"]
            st.write("Route Summary:")
            st.write(f"Length: {(summary['lengthInMeters'] / 1000):.2f} km")
            st.write(f"Travel Time: {(summary['travelTimeInSeconds'] / 60):.2f} minutes")

            # TomTom Map with Debugging
            start_coords = optimizer.get_coordinates(waypoints[0])
            end_coords = optimizer.get_coordinates(waypoints[-1])
            if start_coords and end_coords:
                map_html = f"""
                <!DOCTYPE html>
                <html class='use-all-space'>
                <head>
                    <meta http-equiv='X-UA-Compatible' content='IE=Edge' />
                    <meta charset='UTF-8'>
                    <title>Maps SDK for Web - Vector map</title>
                    <meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no'/>
                    <link rel='stylesheet' type='text/css' href='https://api.tomtom.com/maps-sdk-for-web/cdn/6.x/6.25.1/maps/maps.css'>
                    <style>
                        html.use-all-space, body {{
                            height: 100%;
                            margin: 0;
                            padding: 0;
                            overflow: hidden;
                        }}
                        #map {{
                            height: 500px;
                            width: 100%;
                            background-color: #e0e0e0; /* Light gray background to detect if tiles fail */
                        }}
                        .route-marker {{
                            align-items: center;
                            background-color: #4a90e2;
                            border: solid 3px #2faaff;
                            border-radius: 50%;
                            display: flex;
                            height: 32px;
                            justify-content: center;
                            width: 32px;
                        }}
                        .tt-icon {{
                            height: 30px;
                            width: 30px;
                        }}
                    </style>
                </head>
                <body>
                    <div id='map' class='map'></div>
                    <script src='https://api.tomtom.com/maps-sdk-for-web/cdn/6.x/6.25.1/maps/maps-web.min.js'></script>
                    <script>
                        function isMobileOrTablet() {{
                            return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
                        }}

                        document.addEventListener('DOMContentLoaded', function() {{
                            try {{
                                var map = tt.map({{
                                    key: '{TOMTOM_API_KEY}',
                                    container: 'map',
                                    center: [{start_coords[1]}, {start_coords[0]}],
                                    zoom: 5,
                                    dragPan: !isMobileOrTablet()
                                }});

                                map.on('load', function() {{
                                    var route = {json.dumps(best_route['polyline'])};
                                    var coordinates = route.map(point => [point.longitude, point.latitude]);
                                    var routeLayer = {{
                                        'id': 'route',
                                        'type': 'line',
                                        'source': {{
                                            'type': 'geojson',
                                            'data': {{
                                                'type': 'Feature',
                                                'geometry': {{
                                                    'type': 'LineString',
                                                    'coordinates': coordinates
                                                }}
                                            }}
                                        }},
                                        'paint': {{
                                            'line-color': '#4a90e2',
                                            'line-width': 6
                                        }}
                                    }};

                                    function createMarker(type, lngLat) {{
                                        var element = document.createElement('div');
                                        element.className = 'route-marker';
                                        var inner = document.createElement('div');
                                        inner.className = 'tt-icon -white -' + type;
                                        element.appendChild(inner);
                                        return new tt.Marker({{element: element}}).setLngLat(lngLat);
                                    }}

                                    map.addLayer(routeLayer);
                                    var startMarker = createMarker('start', [{start_coords[1]}, {start_coords[0]}]).addTo(map);
                                    var endMarker = createMarker('finish', [{end_coords[1]}, {end_coords[0]}]).addTo(map);

                                    var bounds = new tt.LngLatBounds();
                                    coordinates.forEach(coord => bounds.extend(coord));
                                    map.fitBounds(bounds, {{ padding: 50 }});

                                    // Debugging: Log successful load
                                    console.log('Map loaded successfully');
                                }});

                                map.addControl(new tt.FullscreenControl());
                                map.addControl(new tt.NavigationControl());

                                // Check if map tiles loaded
                                map.on('error', function(e) {{
                                    console.error('Map error:', e);
                                    document.getElementById('map').innerHTML = '<p>Map failed to load tiles: ' + e.error + '</p>';
                                }});
                            }} catch (error) {{
                                console.error('Map initialization error:', error);
                                document.getElementById('map').innerHTML = '<p>Failed to load map: ' + error.message + '</p>';
                            }}
                        }});
                    </script>
                </body>
                </html>
                """
                st.components.v1.html(map_html, height=510)
            else:
                st.error("Could not generate map due to invalid coordinates.")

        except ValueError as e:
            st.error(f"Error: {str(e)}")
        except Exception as e:
            st.error(f"Unexpected error: {str(e)}")
            logging.error(f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    main()