# Flask application will go here 

import os
import requests
from flask import Flask, request, Response
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

TARGET_SERVER_URL = os.getenv("TARGET_SERVER_URL")

if not TARGET_SERVER_URL:
    raise ValueError("TARGET_SERVER_URL environment variable not set. Please define it in your .env file.")

# Remove hop-by-hop headers
HOP_BY_HOP_HEADERS = [
    'Connection', 'Keep-Alive', 'Proxy-Authenticate', 'Proxy-Authorization',
    'TE', 'Trailers', 'Transfer-Encoding', 'Upgrade',
    # 'Content-Encoding' can also be problematic if not handled carefully,
    # but requests usually handles decompression.
    # 'Content-Length' will be recalculated by requests.
]

@app.route('/wework-callback/', strict_slashes=False, methods=['GET','POST','PUT','DELETE','PATCH','OPTIONS'])
@app.route('/wework-callback',  strict_slashes=False, methods=['GET','POST','PUT','DELETE','PATCH','OPTIONS'])
@app.route('/wework-callback/<path:path>/', strict_slashes=False, methods=['GET','POST','PUT','DELETE','PATCH','OPTIONS'])
@app.route('/wework-callback/<path:path>',  strict_slashes=False, methods=['GET','POST','PUT','DELETE','PATCH','OPTIONS'])
def proxy(path=''):
    if not TARGET_SERVER_URL:
        return "Proxy target not configured.", 500

    # Construct target URL
    target_url = f"{TARGET_SERVER_URL.rstrip('/')}/{path.lstrip('/')}"
    if request.query_string:
        target_url += '?' + request.query_string.decode('utf-8')

    # Prepare headers for the outgoing request
    # Copy original headers and remove hop-by-hop headers
    # Also remove 'Host' as requests will set it based on target_url
    # And 'Content-Length' as requests will calculate it.
    outgoing_headers = {key: value for key, value in request.headers if key.lower() not in ['host', 'content-length'] + [h.lower() for h in HOP_BY_HOP_HEADERS]}

    try:
        # Make the request to the target server
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=outgoing_headers,
            data=request.get_data(),
            params=request.args, # Though query_string is in URL, params can be passed for robustness
            allow_redirects=False, # Forward redirects as they are
            timeout=30 # Set a reasonable timeout (e.g., 30 seconds)
        )

        # Prepare response headers for the client
        # Copy target server's response headers and remove hop-by-hop headers
        response_headers = []
        for key, value in resp.headers.items():
            if key.lower() not in [h.lower() for h in HOP_BY_HOP_HEADERS]:
                response_headers.append((key, value))
        
        # Create Flask response
        # resp.content for binary data, resp.text for text (but content is safer)
        flask_response = Response(resp.content, status=resp.status_code, headers=response_headers)
        return flask_response

    except requests.exceptions.Timeout:
        return "The request to the target server timed out.", 504 # Gateway Timeout
    except requests.exceptions.ConnectionError:
        return "Could not connect to the target server.", 502 # Bad Gateway
    except Exception as e:
        app.logger.error(f"An error occurred: {e}")
        return "An unexpected error occurred while proxying the request.", 500


if __name__ == '__main__':
    port = int(os.getenv("FLASK_RUN_PORT", 8502))
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() in ('true', '1', 't')
    app.run(host='0.0.0.0', port=port, debug=debug_mode) 