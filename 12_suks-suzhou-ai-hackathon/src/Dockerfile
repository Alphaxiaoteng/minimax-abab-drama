# InspectAI S3 在线质检服务镜像。
# 基础镜像选 3.11-slim：比 3.9 略快且无本次代码用到的新语法依赖问题，
# slim 需手动补 opencv 的运行期系统库（libglib2.0-0 / libgl1）。
FROM python:3.11-slim

# apt 非交互 + 装完即清缓存，缩小层体积
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

# 先只拷依赖清单并安装：源码变更时重建不重跑 pip，命中 Docker 层缓存
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 再拷贝三个业务包（inspectai 契约/算法、service API、scripts 启动脚本）
COPY inspectai/ service/ scripts/ ./

EXPOSE 8000

# 健康检查打 /api/v1/health；slim 无 curl，用 stdlib urllib（非 2xx 即抛错→不健康）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=4); sys.exit(0 if r.status==200 else 1)"

CMD ["uvicorn", "service.api:app", "--host", "0.0.0.0", "--port", "8000"]