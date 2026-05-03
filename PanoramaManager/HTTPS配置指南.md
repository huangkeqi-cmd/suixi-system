# HTTPS SSL证书配置指南

## 概述

本文档说明如何为您的影像服务器配置HTTPS，使iPhone访问时不再弹出"需要HTTPS才能启用陀螺仪"的提示。

## 方案一：使用mkcert生成受信任的本地证书（推荐）

### 步骤1：安装mkcert

#### Windows系统：
1. 下载mkcert：
   - 访问 https://github.com/FiloSottile/mkcert/releases
   - 下载Windows版本的mkcert.exe

2. 或者使用Chocolatey安装：
   ```
   choco install mkcert
   ```

3. 或者使用Scoop安装：
   ```
   scoop install mkcert
   ```

#### macOS系统：
```bash
brew install mkcert
brew install nss # 如果使用Firefox
```

#### Linux系统：
```bash
sudo apt install libnss3-tools
brew install mkcert
```

### 步骤2：安装为本地CA

```bash
# 安装为本地受信任的CA
mkcert -install

# 创建证书存储目录
mkdir -p ~/.local/share/mkcert
cd ~/.local/share/mkcert

# 为IP地址生成证书
mkcert 192.168.3.215 127.0.0.1 localhost

# 这会生成：
# - 192.168.3.215+127.0.0.1+localhost.pem (证书)
# - 192.168.3.215+127.0.0.1+localhost-key.pem (私钥)
```

### 步骤3：复制证书到项目目录

```bash
# 复制证书到影像管理器目录
mkdir -p "c:/Users/Administrator/Desktop/随心系统/PanoramaManager/PanoramaMapper-PC/ssl"
cp ~/.local/share/mkcert/*.pem "c:/Users/Administrator/Desktop/随心系统/PanoramaManager/PanoramaMapper-PC/ssl/"
```

## 步骤4：修改Python服务器代码以支持HTTPS

修改 `PanoramaMapper-PC/src/main.py` 中的服务器代码，添加HTTPS支持。

### 修改说明：

1. 找到 `HttpServerThread` 类
2. 在 `__init__` 方法中添加SSL证书参数
3. 在 `run` 方法中创建SSL上下文

**重要提示**：此修改需要重新打包才能生效。

## 步骤5：重启服务器

重新运行程序，服务器将自动使用HTTPS。

---

## 方案二：手动配置Nginx/Apache

如果您使用独立的Nginx或Apache服务器：

### Nginx配置示例：

```nginx
server {
    listen 80;
    server_name 192.168.3.215;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name 192.168.3.215;

    ssl_certificate /path/to/your/certificate.pem;
    ssl_certificate_key /path/to/your/private-key.pem;

    root /path/to/your/viewer/files;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
```

### Apache配置示例：

```apache
<VirtualHost *:80>
    ServerName 192.168.3.215
    Redirect permanent / https://192.168.3.215/
</VirtualHost>

<VirtualHost *:443>
    ServerName 192.168.3.215

    SSLEngine on
    SSLCertificateFile /path/to/your/certificate.pem
    SSLCertificateKeyFile /path/to/your/private-key.pem

    DocumentRoot /path/to/your/viewer/files
    <Directory /path/to/your/viewer/files>
        Options Indexes FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
</VirtualHost>
```

---

## iOS设备安装信任证书

### 方法1：通过邮件安装

1. 将证书文件（.pem）通过邮件发送到iPhone
2. 在iPhone上打开邮件，点击附件
3. 系统会提示"安装配置文件"
4. 点击"安装"并确认
5. 前往 设置 > 通用 > 关于本机 > 证书信任设置
6. 启用对"192.168.3.215"的完全信任

### 方法2：通过Web下载安装

1. 在同一局域网内，使用Safari访问：
   ```
   http://192.168.3.215/certificate.pem
   ```
2. Safari会提示安装描述文件
3. 按照提示完成安装

### 方法3：使用AirDrop传输

1. 将证书文件通过AirDrop发送到iPhone
2. 在iPhone上接受并安装

### 安装后验证

1. 在Safari中访问：`https://192.168.3.215`
2. 如果地址栏显示锁形图标，表示证书已生效
3. 陀螺仪功能应该在HTTPS环境下正常工作

---

## 故障排除

### 问题1：证书不受信任

**原因**：证书没有正确安装或配置

**解决方案**：
- 确保使用mkcert生成证书而不是自签名证书
- 重新运行 `mkcert -install`
- 在iOS设备的"证书信任设置"中启用完全信任

### 问题2：混合内容警告

**原因**：HTTPS页面加载了HTTP资源

**解决方案**：
- 确保所有资源（图片、脚本、样式表）都使用HTTPS加载
- 检查浏览器控制台中的具体警告信息

### 问题3：端口被占用

**原因**：443端口已被其他程序占用

**解决方案**：
- 检查占用443端口的程序：`netstat -ano | findstr :443`
- 停止占用端口的程序或使用其他端口

### 问题4：mkcert命令找不到

**原因**：mkcert未正确安装或未添加到PATH

**解决方案**：
- 重新下载并放置到系统PATH目录
- 使用完整路径执行mkcert

---

## 安全注意事项

1. **私钥保护**：确保私钥文件（-key.pem）安全保管，不要上传或分享
2. **仅限局域网**：此证书仅适用于本地网络，不要用于生产环境
3. **定期更新**：证书通常有有效期，记得定期更新
4. **备份证书**：将证书文件备份到安全位置

---

## 快速验证命令

```bash
# 验证mkcert是否安装成功
mkcert --version

# 验证证书是否已安装为本地CA
mkcert -CAROOT

# 测试服务器是否响应
curl -I https://192.168.3.215
```

---

如有问题，请联系技术支持：
- 微信：amwtuadwe
- 邮箱：376524686@qq.com
- 添加请备注"随心系统"
