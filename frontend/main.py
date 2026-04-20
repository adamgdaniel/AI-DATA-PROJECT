from flask import Flask, render_template, request
import requests
import os

app = Flask(__name__)
API_URL = os.environ['API_URL']


@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        resp = requests.post(f'{API_URL}/login', json={
            'username': request.form['username'],
            'password': request.form['password']
        })
        if resp.status_code == 200:
            return render_template('success.html')
        error = 'Usuario o contraseña incorrectos'
    return render_template('login.html', error=error)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
