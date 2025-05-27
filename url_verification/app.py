import os
from flask import Flask, request, abort
from dotenv import load_dotenv
from crypto_utils import validate_url

# 加载环境变量
load_dotenv()

TOKEN = os.environ.get("TOKEN")
ENCODING_AES_KEY = os.environ.get("ENCODING_AES_KEY")
CORP_ID = os.environ.get("CORP_ID")

# 确保必要配置已加载
if not all([TOKEN, ENCODING_AES_KEY, CORP_ID]):
    raise RuntimeError("Missing environment variables: TOKEN, ENCODING_AES_KEY, CORP_ID")

app = Flask(__name__)

@app.route("/", methods=["GET"])
@app.route("/wework-callback", methods=["GET"])
def verify():
    # 获取请求参数
    msg_signature = request.args.get("msg_signature", "")
    timestamp = request.args.get("timestamp", "")
    nonce = request.args.get("nonce", "")
    echostr = request.args.get("echostr", "")

    # 一步验证 URL
    try:
        plain = validate_url(TOKEN, ENCODING_AES_KEY, CORP_ID,
                             msg_signature, timestamp, nonce, echostr)
    except ValueError as e:
        abort(400, str(e))
    except Exception as e:
        abort(400, f"Decryption error: {str(e)}")
    return plain, 200

@app.route('/wechat_callback', methods=['GET', 'POST'])
def wechat_callback():
    """
    企业微信消息回调接口。
    GET 请求用于 URL 验证。
    POST 请求用于接收业务消息。
    """
    print(f"Callback received request: {request.method} {request.path}")
    print(f"Request Headers: {request.headers}")
    
    # 实际的企业微信开发中，Token, EncodingAESKey, CorpID 需要正确配置
    # sToken = TOKEN
    # sEncodingAESKey = ENCODING_AES_KEY
    # sCorpID = CORP_ID

    # 占位：后续会从 crypto_utils.py 导入并使用 WXBizMsgCrypt
    # from crypto_utils import WXBizMsgCrypt 

    if request.method == 'GET':
        # 企业微信验证URL有效性
        msg_signature = request.args.get('msg_signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        echostr = request.args.get('echostr', '')

        print(f"Received GET for URL validation:")
        print(f"  msg_signature: {msg_signature}")
        print(f"  timestamp: {timestamp}")
        print(f"  nonce: {nonce}")
        print(f"  echostr: {echostr}")

        # 实际验证逻辑 (使用 wxcpt.VerifyURL)
        # ret, sEchoStr = wxcpt.VerifyURL(msg_signature, timestamp, nonce, echostr)
        # if ret == 0:
        #     print("VerifyURL success. Returning echostr to WeCom.")
        #     return sEchoStr, 200
        # else:
        #     print(f"VerifyURL failed. ret: {ret}")
        #     return "VerifyURL failed", 401
            
        # 简化处理：直接返回 echostr，用于打通链路测试
        # 企业微信期望GET请求成功时返回 echostr 参数的内容
        if echostr:
            print(f"Simplified GET: Returning echostr: {echostr}")
            return echostr, 200
        else:
            print("Simplified GET: echostr not found in query parameters.")
            return "Error: echostr not found", 400


    elif request.method == 'POST':
        # 企业微信推送加密消息
        msg_signature = request.args.get('msg_signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        raw_request_data = request.data # 加密的原生请求体 (bytes)

        print(f"Received POST data from WeCom:")
        print(f"  msg_signature: {msg_signature}")
        print(f"  timestamp: {timestamp}")
        print(f"  nonce: {nonce}")
        # print(f"  Request Body (raw encrypted bytes): {raw_request_data}")
        
        try:
            request_body_str = raw_request_data.decode('utf-8')
            print(f"  Request Body (decoded string): {request_body_str}")
        except UnicodeDecodeError:
            print("  Request Body: Could not decode as UTF-8, printing as bytes.")
            print(f"  Request Body (raw bytes): {raw_request_data}")


        # 实际解密逻辑 (使用 wxcpt.DecryptMsg)
        # ret, sMsg = wxcpt.DecryptMsg(request_body_str, msg_signature, timestamp, nonce)
        # if ret == 0:
        #     print(f"Successfully decrypted message: {sMsg}")
        #     # sMsg 是解密后的XML，需要解析并进行业务处理
        #     # ... 您的业务逻辑 ...
        #
        #     # 回复消息 (需要加密)
        #     # resp_xml_content = f"<xml><ToUserName><![CDATA[{'some_user'}]]></ToUserName><FromUserName><![CDATA[{'your_agent'}]]></FromUserName><CreateTime>{timestamp}</CreateTime><MsgType><![CDATA[text]]></MsgType><Text><![CDATA[收到您的消息]]></Text></xml>"
        #     # ret_encrypt, sEncryptMsg = wxcpt.EncryptMsg(resp_xml_content, nonce, timestamp)
        #     # if ret_encrypt == 0:
        #     #     return sEncryptMsg, 200
        #     # else:
        #     #     print(f"Failed to encrypt reply. ret: {ret_encrypt}")
        #     #     return "Failed to encrypt reply", 500
        # else:
        #     print(f"Failed to decrypt message. ret: {ret}")
        #     return "Failed to decrypt message", 401

        # 简化处理：直接返回 "success" 字符串，企业微信要求对 çoğu 消息返回 "success" 或空串
        print("Simplified POST: Processing complete. Returning 'success'.")
        return "success", 200

    return "Unsupported method", 405

if __name__ == '__main__':
    # 监听在 0.0.0.0 意味着应用会接受来自任何网络接口的连接请求。
    # 对于本地开发和frpc转发，这通常是期望的行为。
    # 端口5000是Flask的默认开发端口，您可以根据需要更改。
    # debug=True 会在代码更改时自动重载，并提供调试器，生产环境请务必关闭。
    print("Starting Flask app on 0.0.0.0:8502 with debug mode ON")
    app.run(host='0.0.0.0', port=8502, debug=True) 