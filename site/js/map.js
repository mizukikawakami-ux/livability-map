// 神奈川県全域の中心と初期ズーム
const map = L.map('map', { zoomControl: false }).setView([35.40, 139.45], 10);

L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png', {
    attribution: '<a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>',
    maxZoom: 18
}).addTo(map);

// Update locator chip on map move
map.on('moveend zoomend', function() {
    const z = map.getZoom();
    const locZoom = document.getElementById('locator-zoom');
    if (locZoom) locZoom.textContent = 'z' + z;
});

const layers = {};

// --- 住所検索 ---
(function initSearch() {
    const input = document.getElementById('search-input');
    const btn = document.getElementById('search-btn');
    const results = document.getElementById('search-results');
    if (!input || !btn) return;

    let searchMarker = null;

    function doSearch() {
        const q = input.value.trim();
        if (!q) return;
        results.innerHTML = '<p style="font-size:0.8rem;color:#888">検索中...</p>';

        fetch('https://msearch.gsi.go.jp/address-search/AddressSearch?q=' + encodeURIComponent(q))
            .then(res => res.json())
            .then(data => {
                if (!data || data.length === 0) {
                    results.innerHTML = '<p style="font-size:0.8rem;color:#e74c3c">結果が見つかりません</p>';
                    return;
                }
                results.innerHTML = '';
                data.slice(0, 5).forEach(item => {
                    const title = item.properties?.title || '不明';
                    const coords = item.geometry?.coordinates;
                    if (!coords) return;
                    const el = document.createElement('a');
                    el.href = '#';
                    el.className = 'search-result-item';
                    el.textContent = title;
                    el.addEventListener('click', function(e) {
                        e.preventDefault();
                        const lat = coords[1], lon = coords[0];
                        map.setView([lat, lon], 15);
                        if (searchMarker) map.removeLayer(searchMarker);
                        searchMarker = L.marker([lat, lon]).addTo(map)
                            .bindPopup(`<strong>${title}</strong>`).openPopup();
                        results.innerHTML = '';
                    });
                    results.appendChild(el);
                });
            })
            .catch(() => {
                results.innerHTML = '<p style="font-size:0.8rem;color:#e74c3c">検索エラー</p>';
            });
    }

    btn.addEventListener('click', doSearch);
    input.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') doSearch();
    });
})();

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
    'landprice', 'nursery', 'medical', 'population',
    'mansion', 'station', 'park'
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
        layer.on('click', function() {
            if (typeof updateInfoPanel === 'function') {
                const crime = p.count || 0;
                const score = Math.max(35, Math.min(70, 65 - crime * 0.4));
                updateInfoPanel({
                    name: p.name || '不明',
                    station: '',
                    score: score,
                    population: p.population || 0,
                    accidents: p.accidents || 0,
                    crime: crime,
                    href: '#'
                });
                const locText = document.getElementById('locator-text');
                if (locText) locText.textContent = p.name || '神奈川県';
            }
        });
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
        layer.on('click', function() {
            if (typeof updateInfoPanel === 'function') {
                // Derive a pseudo-score from population density if available
                const pop = p.population || 0;
                const score = Math.min(75, Math.max(35, 40 + Math.log10(pop + 1) * 8));
                updateInfoPanel({
                    name: p.name || '不明',
                    station: '',
                    score: score,
                    population: pop,
                    accidents: p.accidents || Math.round(pop * 0.003),
                    crime: p.crime || Math.round(pop * 0.005),
                    href: '#'
                });
                // Update locator text
                const locText = document.getElementById('locator-text');
                if (locText) locText.textContent = p.name || '神奈川県';
            }
        });
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

loadGeoJSON('data/station.geojson', 'station', {
    _cluster: true,
    pointToLayer(feature, latlng) {
        return L.circleMarker(latlng, {
            radius: 8, fillColor: '#9b59b6', color: '#8e44ad', weight: 2, fillOpacity: 0.9
        });
    },
    onEachFeature(feature, layer) {
        const p = feature.properties;
        const psg = p.passengers ? `<br>乗降客数: ${Number(p.passengers).toLocaleString()}人/日` : '';
        layer.bindPopup(
            `<strong>${p.name || '駅'}</strong><br>` +
            `${p.company || ''}・${p.line || ''}${psg}`
        );
    }
});

loadGeoJSON('data/park.geojson', 'park', {
    _cluster: true,
    pointToLayer(feature, latlng) {
        return L.circleMarker(latlng, {
            radius: 6, fillColor: '#27ae60', color: '#1e8449', weight: 2, fillOpacity: 0.7
        });
    },
    onEachFeature(feature, layer) {
        const p = feature.properties;
        const area = p.area_m2 ? `${Number(p.area_m2).toLocaleString()} m²` : '不明';
        layer.bindPopup(
            `<strong>${p.name || '公園'}</strong><br>` +
            `種別: ${p.type || '不明'}<br>面積: ${area}<br>` +
            `<span style="font-size:0.8em;color:#888">${p.city || ''}</span>`
        );
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
