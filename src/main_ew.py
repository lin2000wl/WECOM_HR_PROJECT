from fastapi import FastAPI, Request, HTTPException, Query, BackgroundTasks
import logging
import uvicorn
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
# import sys # 不再需要
# import os # 不再需要

# 尝试从 src.utils 导入
try:
    from .utils.WXBizMsgCrypt import WXBizMsgCrypt # Relative import
except ImportError as e:
    # 如果导入失败，打印更详细的错误并尝试记录
    # 这里的 logger 可能尚未完全配置好，所以也用 print
    error_msg = f"关键错误: 无法从 src.utils 导入 WXBizMsgCrypt. 请确保该模块及其依赖 (如 pycryptodome) 已正确安装和配置. 错误详情: {e}"
    print(error_msg)
    try:
        logger.critical(error_msg)
    except NameError: # logger 可能还未定义
        pass
    WXBizMsgCrypt = None # 确保后续检查 WXBizMsgCrypt 时不会因 NameError 而崩溃

from . import config_ew # 导入配置模块 # Relative import
from .enterprise_wechat_service import EnterpriseWeChatService
from .core_processor_ew import CoreProcessor
from src.resume_pipeline.trigger import run_pipeline

app = FastAPI(
    title=f"{config_ew.BOT_NAME} - 企业微信API",
    description="接收企业微信回调，并处理相关业务逻辑。",
    version="1.0.0"
)

# 配置日志
logging.basicConfig(level=config_ew.LOG_LEVEL.upper(), format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# TODO: 初始化一个更完善的日志系统，可以从 logger.py 模块导入
print(f"日志级别设置为: {config_ew.LOG_LEVEL}") # 临时打印

# 校验配置是否加载正确
try:
    config_ew.validate_config() # 应用启动时校验一次核心配置
except ValueError as e:
    # logger.critical(f"核心配置校验失败，应用无法启动: {e}")
    print(f"核心配置校验失败，应用可能无法正常工作: {e}") # 临时打印
    # 在生产环境中，这里可能需要更强的错误处理，例如退出应用

# 初始化企业微信服务和核心处理器实例
_ew_service = EnterpriseWeChatService()
_processor = CoreProcessor(_ew_service)

# 初始化 APScheduler
scheduler = AsyncIOScheduler()

async def scheduled_sync_external_contacts():
    """定时任务：为配置的HR用户执行外部联系人同步"""
    if not config_ew.SYNC_HR_USERIDS:
        logger.info("定时同步任务：未配置 SYNC_HR_USERIDS，跳过执行。")
        return

    logger.info(f"定时同步任务：开始为 HR 用户列表 {config_ew.SYNC_HR_USERIDS} 执行外部联系人同步。")
    for hr_userid in config_ew.SYNC_HR_USERIDS:
        if hr_userid.strip(): #确保用户ID有效
            logger.info(f"定时同步任务：正在为 HR 用户 {hr_userid.strip()} 创建同步子任务。")
            try:
                # 直接调用 CoreProcessor 中持有的 SyncProcessor 实例的方法
                # SyncProcessor 的 run_sync_for_hr 已经是异步的，并且内部会处理通知
                await _processor.sync_processor.run_sync_for_hr(hr_userid=hr_userid.strip(), triggered_by_manual_command=False)
                logger.info(f"定时同步任务：为 HR 用户 {hr_userid.strip()} 的同步任务已提交执行。")
            except Exception as e:
                logger.error(f"定时同步任务：为 HR 用户 {hr_userid.strip()} 创建同步子任务时发生错误: {e}")
    logger.info("定时同步任务：所有配置的HR用户的同步任务已处理完毕。")

@app.on_event("startup")
async def startup_event():
    logger.info("应用启动事件：开始配置定时任务...")
    if config_ew.SYNC_SCHEDULE_CRON and config_ew.SYNC_HR_USERIDS:
        try:
            scheduler.add_job(
                scheduled_sync_external_contacts, 
                CronTrigger.from_crontab(config_ew.SYNC_SCHEDULE_CRON),
                id="sync_external_contacts_job", 
                name="定时同步外部联系人",
                replace_existing=True
            )
            scheduler.start()
            logger.info(f"定时同步外部联系人任务已启动，CRON表达式: {config_ew.SYNC_SCHEDULE_CRON}")
        except Exception as e:
            logger.error(f"配置或启动定时同步任务失败: {e}")
    else:
        logger.info("未配置 SYNC_SCHEDULE_CRON 或 SYNC_HR_USERIDS，不启动定时同步任务。")

@app.on_event("shutdown")
async def shutdown_event():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("APScheduler 已关闭。")

@app.get("/", tags=["企业微信回调"], summary="企业微信回调URL验证")
async def verify_wecom_callback(
    msg_signature: str = Query(..., description="企业微信加密签名"),
    timestamp: str = Query(..., description="时间戳"),
    nonce: str = Query(..., description="随机数"),
    echostr: str = Query(..., description="加密的随机字符串，解密后原样返回")
):
    """
    处理企业微信服务器发送的URL验证请求 (GET)。
    企业微信在配置回调URL时，会向填写的URL发送一个GET请求，
    开发者需要解密`echostr`参数并原样返回，以验证URL的有效性。
    """
    # logger.info(
    #     f"收到企业微信URL验证请求: msg_signature={msg_signature}, timestamp={timestamp}, nonce={nonce}, echostr长度={len(echostr)}"
    # )
    print(f"收到企业微信URL验证请求: msg_signature={msg_signature}, timestamp={timestamp}, nonce={nonce}, echostr长度={len(echostr)}") # 临时
    
    try:
        wxcpt = WXBizMsgCrypt(
            sToken=config_ew.WECOM_CALLBACK_TOKEN,
            sEncodingAESKey=config_ew.WECOM_CALLBACK_AES_KEY,
            sReceiveId=config_ew.WECOM_CORP_ID  # 通常是 CorpID，对于ISV是suiteid/corpid
        )
        ret, s_echo_str_bytes = wxcpt.VerifyURL(sMsgSignature=msg_signature, sTimeStamp=timestamp, sNonce=nonce, sEchoStr=echostr)
        
        if ret != 0:
            # logger.error(f"企业微信回调URL验证失败，错误码: {ret}, 返回的 echostr: {s_echo_str_bytes.decode('utf-8') if s_echo_str_bytes else 'N/A'}")
            print(f"企业微信回调URL验证失败，错误码: {ret}") # 临时
            raise HTTPException(status_code=400, detail=f"URL验证失败，错误码: {ret}")
        
        s_echo_str = s_echo_str_bytes.decode('utf-8')
        # logger.info(f"企业微信回调URL验证成功，返回解密后的 echostr: {s_echo_str}")
        print(f"企业微信回调URL验证成功，返回解密后的 echostr: {s_echo_str}") # 临时
        
        # 根据企业微信文档，直接返回解密后的字符串内容作为响应体
        # FastAPI会自动处理Content-Type为text/plain
        # 注意：某些旧文档或实现可能要求返回整数，但新版通常是字符串
        # 确保企业微信后台配置时，能接收到这个字符串。
        return s_echo_str
    except Exception as e:
        # logger.exception("企业微信回调URL验证过程中发生内部异常")
        print(f"企业微信回调URL验证过程中发生内部异常: {e}") # 临时
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")

@app.post("/", tags=["企业微信回调"], summary="企业微信消息接收与处理")
async def receive_wecom_message(
    request: Request, # FastAPI的Request对象，用于获取请求体
    msg_signature: str = Query(..., description="企业微信加密签名"),
    timestamp: str = Query(..., description="时间戳"),
    nonce: str = Query(..., description="随机数")
):
    """
    接收并处理企业微信服务器推送的加密消息 (POST)。
    """
    # logger.info(f"收到企业微信POST消息回调: msg_signature={msg_signature}, timestamp={timestamp}, nonce={nonce}")
    print(f"收到企业微信POST消息回调: msg_signature={msg_signature}, timestamp={timestamp}, nonce={nonce}") # 临时
    try:
        body_bytes = await request.body()
        encrypted_xml_msg = body_bytes.decode('utf-8')
        # logger.debug(f"收到的加密XML消息体: {encrypted_xml_msg}")
        print(f"收到的加密XML消息体 (前200字符): {encrypted_xml_msg[:200]}") # 临时

        wxcpt = WXBizMsgCrypt(
            sToken=config_ew.WECOM_CALLBACK_TOKEN,
            sEncodingAESKey=config_ew.WECOM_CALLBACK_AES_KEY,
            sReceiveId=config_ew.WECOM_CORP_ID
        )

        ret, decrypted_xml_msg_bytes = wxcpt.DecryptMsg(
            sPostData=encrypted_xml_msg, 
            sMsgSignature=msg_signature, 
            sTimeStamp=timestamp, 
            sNonce=nonce
        )

        if ret != 0:
            # logger.error(f"企业微信消息解密失败，错误码: {ret}。密文: {encrypted_xml_msg[:200]}...")
            print(f"企业微信消息解密失败，错误码: {ret}。密文 (前200字符): {encrypted_xml_msg[:200]}...") # 临时
            # 企业微信要求即使解密失败也要回复空字符串或"success"
            # 通常回复空字符串以避免企微持续重试错误的消息
            return "" 

        decrypted_xml_msg = decrypted_xml_msg_bytes.decode('utf-8')
        # logger.info(f"成功解密消息: {decrypted_xml_msg}")
        print(f"成功解密消息 (XML): {decrypted_xml_msg[:300]}") # 临时

        # 1. 解析XML消息 (使用 xmltodict)
        import xmltodict # 在函数内部导入，或者在文件顶部导入
        try:
            parsed_msg_dict = xmltodict.parse(decrypted_xml_msg)['xml'] # 企业微信消息通常在外层有个 <xml> 标签
            # logger.info(f"解析后的消息字典: {parsed_msg_dict}")
            print(f"解析后的消息字典: {parsed_msg_dict}") # 临时
            
            # 提取关键信息示例 (后续将传递给 CoreProcessor)
            msg_type = parsed_msg_dict.get('MsgType')
            from_user_id = parsed_msg_dict.get('FromUserName')
            agent_id = parsed_msg_dict.get('AgentID') # 确认与配置的 AgentID 一致
            # logger.info(f"消息类型: {msg_type}, 发送者: {from_user_id}, AgentID: {agent_id}")
            print(f"消息类型: {msg_type}, 发送者: {from_user_id}, AgentID: {agent_id}")

            if msg_type == 'text':
                content = parsed_msg_dict.get('Content')
                # logger.info(f"文本内容: {content}")
                print(f"文本内容: {content}")
            elif msg_type == 'event':
                event = parsed_msg_dict.get('Event')
                # logger.info(f"事件类型: {event}")
                print(f"事件类型: {event}")
            # 可以根据需要处理更多消息类型 (image, file, voice, video, location, link, etc.)

        except xmltodict.expat.ExpatError as e:
            # logger.error(f"XML消息解析失败 (xmltodict.expat.ExpatError): {e}. XML内容: {decrypted_xml_msg[:300]}")
            print(f"XML消息解析失败 (xmltodict.expat.ExpatError): {e}. XML内容 (前300字符): {decrypted_xml_msg[:300]}")
            # 即使解析失败，也应回复空字符串
            return ""
        except Exception as e:
            # logger.exception(f"消息字典处理过程中发生未知异常. XML内容: {decrypted_xml_msg[:300]}")
            print(f"消息字典处理过程中发生未知异常. XML内容 (前300字符): {decrypted_xml_msg[:300]}, 错误: {e}")
            return ""

        # 将解析后的消息 (parsed_msg_dict) 传递给 CoreProcessor 进行异步处理
        asyncio.create_task(_processor.handle_ew_message(parsed_msg_dict))
        # 企业微信要求在5秒内响应，对于耗时操作应异步处理，并立即回复。
        # 回复空字符串表示成功处理。
        return ""
    except Exception as e:
        # logger.exception("处理企业微信POST消息时发生内部异常")
        print(f"处理企业微信POST消息时发生内部异常: {e}") # 临时
        # 即使发生异常，也应尝试回复空字符串或 "success"，以避免企业微信重试
        return "" 

@app.post("/api/v1/resume/pipeline", tags=["后台简历处理"], summary="手动触发简历处理管道")
async def trigger_resume_pipeline(background_tasks: BackgroundTasks):
    """
    手动触发后台简历处理管道，异步执行所有待处理的简历文件。
    """
    background_tasks.add_task(run_pipeline)
    return {"status": "success", "message": "简历处理管道已在后台执行"}

# 健康检查端点 (可选)
@app.get("/health", tags=["系统"], summary="健康检查")
async def health_check():
    return {"status": "healthy", "bot_name": config_ew.BOT_NAME}

if __name__ == "__main__":
    # logger.info(f"启动 {config_ew.BOT_NAME} 企业微信回调服务器...")
    print(f"启动 {config_ew.BOT_NAME} 企业微信回调服务器...") # 临时
    # 启动Uvicorn服务器
    # host="0.0.0.0" 允许外部访问，port=8502 (或从配置读取)
    # reload=True 用于开发时代码热重载
    uvicorn.run(app, host="0.0.0.0", port=8503, log_level=config_ew.LOG_LEVEL.lower()) 