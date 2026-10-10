"""coze_skills 分发配置.

安装后即可: ``python3 -m coze_skills.cli schema --out coze-plugin-openapi.json``
或 ``python3 -m uvicorn coze_skills.core.server:create_app --factory``
"""

from setuptools import find_packages, setup

setup(
    name="coze-skills",
    version="0.1.0",
    description="扣子 (Coze) 高复用性垂类提效插件工具包",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.9",
    install_requires=[],
    extras_require={"server": ["fastapi>=0.110,<1.0", "uvicorn>=0.27,<1.0"], "dev": ["pytest>=8.0", "httpx>=0.27"]},
    entry_points={"console_scripts": ["coze-skills=coze_skills.cli:main"]},
)
