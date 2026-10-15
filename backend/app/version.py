"""由 brand/sync.py 生成，别手改：改名字改 brand/brand.json，改版本改 VERSION，再跑 python3 brand/sync.py。
MIN_CLIENT 例外：手写，只在新服务器和旧客户端协议不兼容时提高（GET /api/version 发给客户端，低于它的客户端提示更新）。"""
APP_NAME = "Toyuis"
VERSION = "2.95.0"
BUILD = 29500
MIN_CLIENT = "2.86.0"
