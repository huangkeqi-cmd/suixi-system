# 查看当前 Git 代理设置
git config --global http.proxy
git config --global https.proxy

# 如果有输出，立即清除
git config --global --unset http.proxy
git config --global --unset https.proxy

# 同时检查系统环境变量中的代理
echo $env:HTTP_PROXY
echo $env:HTTPS_PROXY