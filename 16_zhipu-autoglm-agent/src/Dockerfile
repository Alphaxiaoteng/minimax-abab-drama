FROM python:3.11-slim

WORKDIR /app

# 核心框架零三方依赖；如需真机/OCR 增强，取消下一行注释安装可选栈
# COPY src/requirements.txt /app/requirements.txt
# RUN pip install --no-cache-dir -r requirements.txt

COPY src/ /app/

ENV PYTHONPATH=/app \
    AUTOGLM_ALLOW_OFFLINE=1

CMD ["python", "run_demo.py"]
