const map = L.map('map').setView([35.568, 139.517], 14);

L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png', {
    attribution: '<a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>',
    maxZoom: 18
}).addTo(map);

const layers = {};

// --- Tile-based layers (hazard maps) ---

layers.flood = L.tileLayer(
    'https://disaportaldata.gsi.go.jp/raster/01_flood_l2_shinsuishin_data/{z}/{x}/{y}.png',
    { opacity: 0.6, maxZoom: 17 }
);

layers.landslide = L.tileLayer(
    'https://disaportaldata.gsi.go.jp/raster/05_dosekiryukeikaikuiki/{z}/{x}/{y}.png',
    { opacity: 0.6, maxZoom: 17 }
);

// --- GeoJSON-based layers ---

function loadGeoJSON(url, layerName, options) {
    fetch(url)
        .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        })
        .then(data => {
            const useCluster = options._cluster;
            delete options._cluster;

            if (useCluster && typeof L.markerClusterGroup === 'function') {
                const clusterGroup = L.markerClusterGroup({
                    maxClusterRadius: 40,
                    disableClusteringAtZoom: 16
                });
                const geoLayer = L.geoJSON(data, options);
                clusterGroup.addLayer(geoLayer);
                layers[layerName] = clusterGroup;
            } else {
                layers[layerName] = L.geoJSON(data, options);
            }

            const checkbox = document.getElementById('layer-' + layerName);
            if (checkbox && checkbox.checked) {
                layers[layerName].addTo(map);
            }
        })
        .catch(err => console.warn(`${layerName}: ${err.message}`));
}

function setupLayerToggle(name) {
    const checkbox = document.getElementById('layer-' + name);
    if (!checkbox) return;

    checkbox.addEventListener('change', function () {
        if (this.checked && layers[name]) {
            layers[name].addTo(map);
        } else if (layers[name]) {
            map.removeLayer(layers[name]);
        }
    });
}

const allLayerNames = [
    'accidents', 'flood', 'landslide', 'crime',
    'landprice', 'nursery', 'medical', 'population', 'mansion'
];
allLayerNames.forEach(setupLayerToggle);

// --- Load GeoJSON data ---

loadGeoJSON('data/accidents.geojson', 'accidents', {
    _cluster: true,
    pointToLayer(feature, latlng) {
        return L.circleMarker(latlng, {
            radius: 5,
            fillColor: '#e74c3c',
            color: '#c0392b',
            weight: 1,
            fillOpacity: 0.7
        });
    },
    onEachFeature(feature, layer) {
        const p = feature.properties;
        const severity = p.severity ? `<br>程度: ${p.severity}` : '';
        layer.bindPopup(
            `<strong>交通事故</strong><br>発生日: ${p.date || '不明'}<br>類型: ${p.type || '不明'}${severity}<br>天候: ${p.weather || '不明'}`
        );
    }
});

loadGeoJSON('data/crime_map.geojson', 'crime', {
    style(feature) {
        const count = feature.properties.count || 0;
        const color = count > 20 ? '#c0392b' : count > 10 ? '#e74c3c' : count > 5 ? '#f39c12' : '#2ecc71';
        return { fillColor: color, fillOpacity: 0.4, color: '#666', weight: 1 };
    },
    onEachFeature(feature, layer) {
        const p = feature.properties;
        const detail = p.breakdown ? `<br><span style="font-size:0.8em;color:#666">${p.breakdown}</span>` : '';
        layer.bindPopup(`<strong>${p.name || ''}</strong><br>犯罪件数: ${p.count || 0}件${detail}`);
    }
});

loadGeoJSON('data/population.geojson', 'population', {
    style(feature) {
        const pop = feature.properties.population || 0;
        const color = pop > 5000 ? '#1a237e' : pop > 3000 ? '#283593' : pop > 1000 ? '#3f51b5' : '#9fa8da';
        return { fillColor: color, fillOpacity: 0.35, color: '#333', weight: 1 };
    },
    onEachFeature(feature, layer) {
        const p = feature.properties;
        layer.bindPopup(
            `<strong>${p.name || ''}</strong><br>` +
            `人口: ${(p.population || 0).toLocaleString()}人<br>` +
            `世帯数: ${(p.households || 0).toLocaleString()}世帯`
        );
    }
});

loadGeoJSON('data/landprice.geojson', 'landprice', {
    _cluster: true,
    pointToLayer(feature, latlng) {
        return L.circleMarker(latlng, {
            radius: 8, fillColor: '#2ecc71', color: '#27ae60', weight: 2, fillOpacity: 0.8
        });
    },
    onEachFeature(feature, layer) {
        const p = feature.properties;
        const price = p.price ? Number(p.price).toLocaleString() : '不明';
        const change = p.change ? ` (前年比${p.change})` : '';
        layer.bindPopup(
            `<strong>地価公示</strong><br>価格: ${price}円/m²${change}<br>` +
            `用途: ${p.use || '不明'}<br>` +
            `<span style="font-size:0.8em;color:#888">${p.address || ''}</span>`
        );
    }
});

loadGeoJSON('data/nursery.geojson', 'nursery', {
    _cluster: true,
    pointToLayer(feature, latlng) {
        return L.circleMarker(latlng, {
            radius: 7, fillColor: '#f39c12', color: '#e67e22', weight: 2, fillOpacity: 0.8
        });
    },
    onEachFeature(feature, layer) {
        const p = feature.properties;
        layer.bindPopup(`<strong>${p.name || '保育施設'}</strong><br>定員: ${p.capacity || '不明'}人<br>住所: ${p.address || ''}`);
    }
});

loadGeoJSON('data/medical.geojson', 'medical', {
    _cluster: true,
    pointToLayer(feature, latlng) {
        return L.circleMarker(latlng, {
            radius: 6, fillColor: '#1abc9c', color: '#16a085', weight: 2, fillOpacity: 0.8
        });
    },
    onEachFeature(feature, layer) {
        const p = feature.properties;
        layer.bindPopup(`<strong>${p.name || '医療施設'}</strong><br>種別: ${p.type || '不明'}<br>診療科: ${p.department || '不明'}`);
    }
});

loadGeoJSON('data/mansion.geojson', 'mansion', {
    pointToLayer(feature, latlng) {
        return L.circleMarker(latlng, {
            radius: 9, fillColor: '#e91e63', color: '#c2185b', weight: 2, fillOpacity: 0.8
        });
    },
    onEachFeature(feature, layer) {
        const p = feature.properties;
        layer.bindPopup(
            `<strong>${p.name || '新築マンション'}</strong><br>` +
            `状況: ${p.status || '不明'}<br>` +
            `竣工予定: ${p.completion || '不明'}<br>` +
            `規模: ${p.scale || '不明'}<br>` +
            `<span style="font-size:0.8em;color:#888">事業者: ${p.developer || '不明'}</span>`
        );
    }
});
