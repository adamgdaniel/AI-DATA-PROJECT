from flask import Flask, render_template, request, session, jsonify, redirect, url_for
import requests
import math
import os

app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']
API_URL = os.environ['API_URL']
IOT_API_URL = os.environ.get('IOT_API_URL', '')
AEMET_API_KEY = os.environ.get('AEMET_API_KEY', '')
AEMET_BASE = 'https://opendata.aemet.es/openapi/api'

# Código INE de la capital de cada provincia (fallback cuando el municipio no tiene previsión)
PROVINCE_CAPITALS = {
    '01':'01059','02':'02003','03':'03014','04':'04013','05':'05019',
    '06':'06015','07':'07040','08':'08019','09':'09059','10':'10037',
    '11':'11012','12':'12040','13':'13034','14':'14021','15':'15030',
    '16':'16078','17':'17079','18':'18087','19':'19130','20':'20069',
    '21':'21041','22':'22125','23':'23050','24':'24089','25':'25120',
    '26':'26089','27':'27028','28':'28079','29':'29067','30':'30030',
    '31':'31201','32':'32054','33':'33044','34':'34120','35':'35016',
    '36':'36038','37':'37274','38':'38038','39':'39075','40':'40194',
    '41':'41091','42':'42173','43':'43148','44':'44216','45':'45168',
    '46':'46250','47':'47186','48':'48020','49':'49275','50':'50297',
}
SIGPAC_HEADERS = {'Referer': 'https://sigpac.mapa.gob.es/fega/visor/', 'User-Agent': 'Mozilla/5.0'}


def _lat_lng_to_tile(lat, lng, zoom):
    n = 2 ** zoom
    x = int((lng + 180) / 360 * n)
    lat_r = math.radians(lat)
    xyz_y = int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n)
    tms_y = n - 1 - xyz_y  # SIGPAC uses TMS (Y axis inverted vs standard XYZ)
    return x, tms_y


def _to_mercator(lat, lng):
    x = lng * 20037508.342789244 / 180
    y = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180)
    y = y * 20037508.342789244 / 180
    return x, y


def _from_mercator(x, y):
    lng = x * 180 / 20037508.342789244
    lat = math.degrees(2 * math.atan(math.exp(y * math.pi / 20037508.342789244)) - math.pi / 2)
    return lat, lng


def _convert_geometry(geom):
    if not geom:
        return None
    def conv_ring(ring):
        result = []
        for pt in ring:
            lat, lng = _from_mercator(pt[0], pt[1])
            result.append([lng, lat])
        return result
    t = geom.get('type', '')
    if t == 'Polygon':
        return {'type': 'Polygon', 'coordinates': [conv_ring(r) for r in geom['coordinates']]}
    if t == 'MultiPolygon':
        return {'type': 'MultiPolygon', 'coordinates': [[conv_ring(r) for r in poly] for poly in geom['coordinates']]}
    return None


def _point_in_ring(px, py, ring):
    inside = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        resp = requests.post(f'{API_URL}/login', json={
            'username': request.form['username'],
            'password': request.form['password']
        })
        if resp.status_code == 200:
            session['user_id'] = resp.json().get('user_id', 1)
            return redirect(url_for('mapa'))
        error = 'Usuario o contraseña incorrectos'
    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html', errors={})
    errors = {}
    username = request.form.get('username', '').strip()
    email    = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    password2 = request.form.get('password2', '')
    if password != password2:
        errors['password2'] = 'Las contraseñas no coinciden'
        return render_template('register.html', errors=errors)
    resp = requests.post(f'{API_URL}/register', json={
        'username': username, 'email': email, 'password': password
    })
    if resp.status_code == 201 or resp.status_code == 200:
        return redirect(url_for('login'))
    data = resp.json()
    if 'field' in data:
        errors[data['field']] = data.get('error', 'Error al registrarse')
    else:
        errors['username'] = data.get('error', 'Error al registrarse')
    return render_template('register.html', errors=errors)


@app.route('/mapa')
def mapa():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('success.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/sigpac-info')
def sigpac_info():
    lat = float(request.args.get('lat'))
    lng = float(request.args.get('lng'))
    tile_zoom = 15
    tx, ty = _lat_lng_to_tile(lat, lng, tile_zoom)
    tile_url = f'https://sigpac.mapa.gob.es/vectorsdg/vector/parcela@3857/{tile_zoom}.{tx}.{ty}.geojson'

    try:
        resp = requests.get(tile_url, headers=SIGPAC_HEADERS, timeout=8)
        print(f"[SIGPAC tile] {resp.status_code} | {tile_url}")
        if resp.status_code != 200:
            return jsonify({'features': []}), 200

        geojson = resp.json()
        px, py = _to_mercator(lat, lng)
        features = geojson.get('features', [])
        print(f"[SIGPAC tile] {len(features)} features | click mercator: ({px:.0f}, {py:.0f})")
        print(f"[SIGPAC tile raw] {resp.text[:300]}")
        if features:
            first_geom = features[0].get('geometry', {})
            first_coords = first_geom.get('coordinates', [[]])[0]
            if first_coords:
                print(f"[SIGPAC tile] first ring sample: {first_coords[:2]}")
        found_props = None

        found_geom = None
        for feature in features:
            geom = feature.get('geometry', {})
            coords = geom.get('coordinates', [])
            hit = False
            if geom.get('type') == 'Polygon':
                hit = _point_in_ring(px, py, coords[0])
            elif geom.get('type') == 'MultiPolygon':
                hit = any(_point_in_ring(px, py, poly[0]) for poly in coords)
            if hit:
                found_props = feature.get('properties', {})
                found_geom = geom
                print(f"[SIGPAC tile props] {found_props}")
                break

        if not found_props:
            return jsonify({'features': []}), 200

        p = found_props
        prov = p.get('provincia', p.get('prov', p.get('PROVINCIA', '')))
        mun  = p.get('municipio',  p.get('mun',  p.get('MUNICIPIO', '')))
        agr  = p.get('agregado',   p.get('agr',  0))
        zon  = p.get('zona',       p.get('zon',  0))
        pol  = p.get('poligono',   p.get('pol',  p.get('POLIGONO', '')))
        par  = p.get('parcela',    p.get('par',  p.get('PARCELA', '')))
        ref  = f"{prov},{mun},{agr},{zon},{pol},{par}"

        info_url = f'https://sigpac.mapa.gob.es/fega/serviciosvisorsigpac/layerinfo/parcela/{ref}/'
        info_resp = requests.get(info_url, headers=SIGPAC_HEADERS, timeout=5)
        print(f"[SIGPAC info] {info_resp.status_code} | {info_url} | {info_resp.text[:400]}")

        if info_resp.status_code != 200:
            return jsonify({'features': [{'properties': found_props}]}), 200

        info = info_resp.json()
        ids = info.get('id', [])
        parcela_info = info.get('parcelaInfo', {})
        first_recinto = (info.get('query') or [{}])[0]

        normalized = {
            'provincia': int(ids[0]) if len(ids) > 0 else prov,
            'municipio':  int(ids[1]) if len(ids) > 1 else mun,
            'agregado':   int(ids[2]) if len(ids) > 2 else agr,
            'zona':       int(ids[3]) if len(ids) > 3 else zon,
            'poligono':   int(ids[4]) if len(ids) > 4 else pol,
            'parcela':    int(ids[5]) if len(ids) > 5 else par,
            'recinto':    first_recinto.get('recinto', 1),
            'superficie': round((parcela_info.get('dn_surface') or 0) / 10000, 4),
            'uso_sigpac': first_recinto.get('uso_sigpac', ''),
            'lat': lat,
            'lng': lng,
            'geometry': _convert_geometry(found_geom)
        }
        return jsonify({'features': [{'properties': normalized}]})

    except Exception as e:
        print(f"[SIGPAC] Error: {e}")
        return jsonify({'features': []}), 200


@app.route('/mis-parcelas')
def mis_parcelas():
    if 'user_id' not in session:
        return jsonify({'error': 'no autenticado'}), 401
    try:
        resp = requests.get(f'{API_URL}/parcelas', params={'user_id': session['user_id']})
        return jsonify(resp.json()), resp.status_code
    except Exception:
        return jsonify([]), 200


@app.route('/registrar-parcela', methods=['POST'])
def registrar_parcela():
    if 'user_id' not in session:
        return jsonify({'error': 'no autenticado'}), 401
    data = request.json
    data['user_id'] = session['user_id']
    resp = requests.post(f'{API_URL}/parcelas', json=data)
    try:
        return jsonify(resp.json()), resp.status_code
    except Exception:
        return jsonify({'error': f'API no disponible (status {resp.status_code})'}), 502


@app.route('/parcela/<parcela_id>')
def detalle_parcela(parcela_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    try:
        resp = requests.get(f'{API_URL}/parcelas', params={'user_id': session['user_id']})
        parcelas = resp.json()
        parcela = next((p for p in parcelas if p['parcela_id'] == parcela_id), None)
    except Exception:
        parcela = None
    if not parcela:
        return redirect(url_for('mapa'))
    return render_template('parcela_detail.html', parcela=parcela)


@app.route('/parcela/<parcela_id>/grid', methods=['POST'])
def update_grid(parcela_id):
    if 'user_id' not in session:
        return jsonify({'error': 'no autenticado'}), 401
    data = request.json
    data['user_id'] = session['user_id']
    resp = requests.post(f'{API_URL}/parcelas/{parcela_id}/grid', json=data)
    try:
        return jsonify(resp.json()), resp.status_code
    except Exception:
        return jsonify({'error': 'API error'}), 502


@app.route('/parcela/<parcela_id>/zona', methods=['POST'])
def añadir_zona(parcela_id):
    if 'user_id' not in session:
        return jsonify({'error': 'no autenticado'}), 401
    data = request.json
    data['user_id'] = session['user_id']
    resp = requests.post(f'{API_URL}/parcelas/{parcela_id}/zona', json=data)
    try:
        return jsonify(resp.json()), resp.status_code
    except Exception:
        return jsonify({'error': 'API error'}), 502


@app.route('/parcela/<parcela_id>/zona/<zona_id>', methods=['DELETE'])
def eliminar_zona(parcela_id, zona_id):
    if 'user_id' not in session:
        return jsonify({'error': 'no autenticado'}), 401
    resp = requests.delete(
        f'{API_URL}/parcelas/{parcela_id}/zona/{zona_id}',
        json={'user_id': session['user_id']}
    )
    try:
        return jsonify(resp.json()), resp.status_code
    except Exception:
        return jsonify({'error': 'API error'}), 502


@app.route('/tiempo-parcela')
def tiempo_parcela():
    if 'user_id' not in session:
        return jsonify({'error': 'no autenticado'}), 401
    lat = request.args.get('lat')
    lng = request.args.get('lng')
    if not lat or not lng:
        return jsonify({'error': 'lat y lng requeridos'}), 400
    try:
        r = requests.get(
            'https://api.open-meteo.com/v1/forecast',
            params={
                'latitude': lat,
                'longitude': lng,
                'daily': 'temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode',
                'timezone': 'auto',
                'forecast_days': 7
            },
            timeout=8
        )
        return jsonify(r.json()), r.status_code
    except Exception as e:
        print(f"[OpenMeteo] Error: {e}")
        return jsonify({'error': 'Error consultando Open-Meteo'}), 502


@app.route('/home-assistant', methods=['GET'])
def home_assistant():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    connections = []
    if IOT_API_URL:
        try:
            resp = requests.get(f'{IOT_API_URL}/ha/connections', params={'user_id': session['user_id']})
            if resp.status_code == 200:
                connections = resp.json()
        except Exception:
            pass
    return render_template('ha_connect.html',
                           connections=connections,
                           success=request.args.get('success'),
                           form_error=None)


@app.route('/home-assistant/conectar', methods=['POST'])
def ha_conectar():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    ha_url    = request.form.get('ha_url', '').strip()
    ha_token  = request.form.get('ha_token', '').strip()
    display_name = request.form.get('display_name', '').strip() or None
    if not ha_url or not ha_token:
        return render_template('ha_connect.html', connections=[],
                               success=None, form_error='URL y token son obligatorios.')
    if not IOT_API_URL:
        return render_template('ha_connect.html', connections=[],
                               success=None, form_error='Servicio IoT no configurado.')
    try:
        resp = requests.post(f'{IOT_API_URL}/ha/connect', json={
            'user_id': session['user_id'],
            'ha_url': ha_url,
            'ha_token': ha_token,
            'display_name': display_name
        })
        if resp.status_code == 201:
            return redirect(url_for('home_assistant', success='1'))
        form_error = resp.json().get('error', 'Error al conectar.')
    except Exception:
        form_error = 'No se pudo contactar con el servicio IoT.'
    return render_template('ha_connect.html', connections=[], success=None, form_error=form_error)


@app.route('/home-assistant/eliminar/<int:connection_id>', methods=['POST'])
def ha_eliminar_conexion(connection_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if IOT_API_URL:
        try:
            requests.delete(f'{IOT_API_URL}/ha/connections/{connection_id}',
                            params={'user_id': session['user_id']})
        except Exception:
            pass
    return redirect(url_for('home_assistant'))


@app.route('/mis-conexiones-ha')
def mis_conexiones_ha():
    if 'user_id' not in session:
        return jsonify({'error': 'no autenticado'}), 401
    if not IOT_API_URL:
        return jsonify([]), 200
    try:
        resp = requests.get(f'{IOT_API_URL}/ha/connections', params={'user_id': session['user_id']})
        return jsonify(resp.json()), resp.status_code
    except Exception:
        return jsonify([]), 200


@app.route('/iot/descubrir-sensores')
def iot_descubrir_sensores():
    if 'user_id' not in session:
        return jsonify({'error': 'no autenticado'}), 401
    connection_id = request.args.get('connection_id')
    if not connection_id or not IOT_API_URL:
        return jsonify([]), 200
    try:
        resp = requests.get(f'{IOT_API_URL}/ha/sensores/discover',
                            params={'connection_id': connection_id}, timeout=20)
        return jsonify(resp.json()), resp.status_code
    except Exception:
        return jsonify({'error': 'Error contactando IoT API'}), 502


@app.route('/iot/registrar-sensor', methods=['POST'])
def iot_registrar_sensor():
    if 'user_id' not in session:
        return jsonify({'error': 'no autenticado'}), 401
    if not IOT_API_URL:
        return jsonify({'error': 'Servicio IoT no configurado'}), 503
    data = request.json
    data['user_id'] = session['user_id']
    try:
        resp = requests.post(f'{IOT_API_URL}/ha/sensores', json=data)
        return jsonify(resp.json()), resp.status_code
    except Exception:
        return jsonify({'error': 'Error contactando IoT API'}), 502


@app.route('/iot/mis-sensores')
def iot_mis_sensores():
    if 'user_id' not in session:
        return jsonify({'error': 'no autenticado'}), 401
    if not IOT_API_URL:
        return jsonify([]), 200
    parcela_usuario_id = request.args.get('parcela_usuario_id')
    params = {'parcela_usuario_id': parcela_usuario_id} if parcela_usuario_id \
             else {'user_id': session['user_id']}
    try:
        resp = requests.get(f'{IOT_API_URL}/ha/sensores', params=params)
        return jsonify(resp.json()), resp.status_code
    except Exception:
        return jsonify([]), 200


@app.route('/iot/eliminar-sensor', methods=['POST'])
def iot_eliminar_sensor():
    if 'user_id' not in session:
        return jsonify({'error': 'no autenticado'}), 401
    if not IOT_API_URL:
        return jsonify({'error': 'Servicio IoT no configurado'}), 503
    sensor_id = request.json.get('sensor_id')
    try:
        resp = requests.delete(f'{IOT_API_URL}/ha/sensores',
                               params={'sensor_id': sensor_id, 'user_id': session['user_id']})
        return jsonify(resp.json()), resp.status_code
    except Exception:
        return jsonify({'error': 'Error contactando IoT API'}), 502


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
