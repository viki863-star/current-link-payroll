from app import create_app

app = create_app()

if __name__ == "__main__":
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    from waitress import serve
    serve(app, host="0.0.0.0", port=7860, threads=3)
