import folium
from folium.plugins import HeatMap


def generate_map(events):

    m = folium.Map(location=[20, 0], zoom_start=2)

    heat_data = []

    for e in events:

        lat = e.get("lat")
        lon = e.get("lon")

        if lat and lon:

            if e["score"] > 8:
                color = "red"
            elif e["score"] > 6:
                color = "orange"
            else:
                color = "yellow"

            tooltip = f"{e['title']} | Score {e['score']} | {e['category']}"

            folium.CircleMarker(
                location=[lat, lon],
                radius=7,
                color=color,
                fill=True,
                tooltip=tooltip
            ).add_to(m)

            heat_data.append([lat, lon, e["score"] * 2])

    if heat_data:
        HeatMap(
            heat_data,
            radius=35,
            blur=30,
            min_opacity=0.3,
            max_zoom=4
        ).add_to(m)
        
    folium.LayerControl().add_to(m)

    m.save("geopolitical_map.html")