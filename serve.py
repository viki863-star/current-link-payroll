import os

from app import create_app


app = create_app()


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))

    try:
        from waitress import serve
    except ImportError:
        app.run(host=host, port=port, debug=False)
    else:
        serve(app, host=host, port=port)
