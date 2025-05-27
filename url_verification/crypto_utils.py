import hashlib
import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


def verify_signature(token: str, timestamp: str, nonce: str, msg_signature: str, echostr: str) -> bool:
    """
    验证企业微信回调 URL 签名。
    参数:
      token: 企业微信配置的 TOKEN
      timestamp: 请求中的 timestamp
      nonce: 请求中的 nonce
      msg_signature: 请求中的 msg_signature
      echostr: 请求中的 echostr（加密的随机串）
    返回:
      bool: 签名校验是否通过
    """
    arr = [token, timestamp, nonce, echostr]
    arr.sort()
    s = ''.join(arr)
    return hashlib.sha1(s.encode('utf-8')).hexdigest() == msg_signature 


def decrypt_echostr(encrypted: str, encoding_aes_key: str, corp_id: str) -> str:
    """
    解密企业微信回调 URL 中的 echostr。
    参数:
      encrypted: 请求中的 echostr（Base64 编码的密文）
      encoding_aes_key: 企业微信配置的 EncodingAESKey（43 个字符）
      corp_id: 企业微信 CorpID
    返回:
      str: 解密后原始 echostr 明文
    """
    # base64 解码获取 AES 密钥
    key = base64.b64decode(encoding_aes_key + '=')
    iv = key[:16]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    # 解密并去除 PKCS7 填充
    decoded = base64.b64decode(encrypted)
    decrypted = cipher.decrypt(decoded)
    plaintext = unpad(decrypted, AES.block_size)
    # 去除 16 字节随机前缀，读取 4 字节网络字节序长度
    msg_len = int.from_bytes(plaintext[16:20], 'big')
    # 提取 echostr
    echo = plaintext[20:20+msg_len].decode('utf-8')
    # 校验 CorpID
    received_corp_id = plaintext[20+msg_len:].decode('utf-8')
    if received_corp_id != corp_id:
        raise ValueError('CorpID 校验失败')
    return echo 


def validate_url(token: str, encoding_aes_key: str, corp_id: str,
                 msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
    """
    一步完成回调 URL 验证：
    1. 校验签名；
    2. 解密 echostr 获得明文；
    返回解密后的随机串或抛出异常。
    """
    # 签名校验
    arr = [token, timestamp, nonce, echostr]
    arr.sort()
    s = ''.join(arr)
    if hashlib.sha1(s.encode('utf-8')).hexdigest() != msg_signature:
        raise ValueError('签名校验失败')
    # echostr 解密
    key = base64.b64decode(encoding_aes_key + '=')
    iv = key[:16]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decoded = base64.b64decode(echostr)
    decrypted = cipher.decrypt(decoded)
    plaintext = unpad(decrypted, AES.block_size)
    # 解析随机串长度和明文
    msg_len = int.from_bytes(plaintext[16:20], 'big')
    echo = plaintext[20:20+msg_len].decode('utf-8')
    # 校验 CorpID
    received_corp_id = plaintext[20+msg_len:].decode('utf-8')
    if received_corp_id != corp_id:
        raise ValueError('CorpID 校验失败')
    return echo 