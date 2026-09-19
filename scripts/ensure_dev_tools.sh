#!/bin/bash
# ============================================================
# 开发环境工具检查 & 自动安装脚本
# 目标：确保 JDK 17 + Maven 3 + Node.js 18+ 已就绪
# 使用方式：bash scripts/ensure_dev_tools.sh
# 支持系统：Ubuntu 20.04+ / Debian 11+
# 设计原则：幂等执行 —— 已安装则跳过，未安装则自动补全
# ============================================================

set -eo pipefail

# 检查必需工具
for tool in wget curl apt-get; do
    if ! command -v $tool &> /dev/null; then
        echo "[ERROR] 必需工具 $tool 未安装，请先安装后重试"
        echo "  安装命令: sudo apt-get install -y wget curl"
        exit 1
    fi
done

# 获取实际用户 home 目录（sudo 时 HOME 会变成 /root）
REAL_USER="${SUDO_USER:-${USER:-$(whoami)}}"
REAL_HOME=$(eval echo "~$REAL_USER")

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }

# ============================================================
# 版本要求
# ============================================================
REQUIRED_JDK_MAJOR=17
REQUIRED_MAVEN_MAJOR=3
REQUIRED_NODE_MAJOR=18
MAVEN_VERSION="3.9.6"
NODE_MAJOR_VERSION=20

NEED_INSTALL_JDK=false
NEED_INSTALL_MAVEN=false
NEED_INSTALL_NODE=false

# ============================================================
# 检查 JDK
# ============================================================
check_jdk() {
    log_info "检查 JDK..."

    if command -v java &> /dev/null; then
        JAVA_VER=$(java -version 2>&1 | head -1 | awk -F'"' '{print $2}' | cut -d'.' -f1)
        if [ "$JAVA_VER" -ge "$REQUIRED_JDK_MAJOR" ] 2>/dev/null; then
            log_ok "JDK $JAVA_VER 已安装（满足 >= $REQUIRED_JDK_MAJOR 要求）"
            return 0
        else
            log_warn "JDK 版本 $JAVA_VER 不满足要求（需要 >= $REQUIRED_JDK_MAJOR）"
        fi
    else
        log_warn "未检测到 java 命令"
    fi

    NEED_INSTALL_JDK=true
    return 1
}

# ============================================================
# 检查 Maven
# ============================================================
check_maven() {
    log_info "检查 Maven..."

    if command -v mvn &> /dev/null; then
        MVN_VER=$(mvn -version 2>&1 | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
        MVN_MAJOR=$(echo "$MVN_VER" | cut -d'.' -f1)
        if [ "$MVN_MAJOR" -ge "$REQUIRED_MAVEN_MAJOR" ] 2>/dev/null; then
            log_ok "Maven $MVN_VER 已安装（满足 >= $REQUIRED_MAVEN_MAJOR 要求）"
            return 0
        else
            log_warn "Maven 版本 $MVN_VER 不满足要求（需要 >= $REQUIRED_MAVEN_MAJOR）"
        fi
    else
        log_warn "未检测到 mvn 命令"
    fi

    NEED_INSTALL_MAVEN=true
    return 1
}

# ============================================================
# 安装 JDK 17（Temurin，清华源加速）
# ============================================================
install_jdk() {
    log_info "开始安装 JDK $REQUIRED_JDK_MAJOR..."

    # 检查 root 权限
    if [ "$EUID" -ne 0 ]; then
        log_error "安装 JDK 需要 root 权限，请使用 sudo 运行"
        log_info "手动安装命令："
        echo "  sudo apt-get update"
        echo "  sudo apt-get install -y temurin-17-jdk"
        echo "  # 或: sudo apt-get install -y openjdk-17-jdk"
        return 1
    fi

    # 检测系统
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_ID=$ID
        OS_CODENAME=$VERSION_CODENAME
    else
        log_error "无法检测操作系统版本"
        return 1
    fi

    # 尝试方案1: Eclipse Temurin（清华源）
    log_info "尝试从清华源安装 Eclipse Temurin JDK $REQUIRED_JDK_MAJOR..."
    if wget -qO- https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor -o /usr/share/keyrings/adoptium-keyring.gpg 2>/dev/null; then
        echo "deb [signed-by=/usr/share/keyrings/adoptium-keyring.gpg] https://mirrors.tuna.tsinghua.edu.cn/Adoptium/deb ${OS_CODENAME} main" > /etc/apt/sources.list.d/adoptium.list
        apt-get update -qq
        if apt-get install -y -qq temurin-17-jdk; then
            # 设置 JAVA_HOME
            cat > /etc/profile.d/java.sh << 'EOF'
export JAVA_HOME=/usr/lib/jvm/temurin-17-jdk-amd64
export PATH=$JAVA_HOME/bin:$PATH
EOF
            source /etc/profile.d/java.sh 2>/dev/null || true
            log_ok "JDK 17 (Temurin) 安装成功"
            return 0
        fi
    fi

    # 尝试方案2: OpenJDK（APT 默认源）
    log_info "Temurin 源不可用，回退到 OpenJDK..."
    apt-get update -qq
    if apt-get install -y -qq openjdk-17-jdk; then
        cat > /etc/profile.d/java.sh << 'EOF'
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH=$JAVA_HOME/bin:$PATH
EOF
        source /etc/profile.d/java.sh 2>/dev/null || true
        log_ok "JDK 17 (OpenJDK) 安装成功"
        return 0
    fi

    log_error "JDK 安装失败"
    return 1
}

# ============================================================
# 安装 Maven 3（阿里云镜像加速）
# ============================================================
install_maven() {
    log_info "开始安装 Maven ${MAVEN_VERSION}..."

    # 检查 root 权限
    if [ "$EUID" -ne 0 ]; then
        log_error "安装 Maven 需要 root 权限，请使用 sudo 运行"
        log_info "手动安装命令："
        echo "  wget https://archive.apache.org/dist/maven/maven-3/${MAVEN_VERSION}/binaries/apache-maven-${MAVEN_VERSION}-bin.tar.gz -O /tmp/maven.tar.gz"
        echo "  sudo tar -xzf /tmp/maven.tar.gz -C /opt/"
        echo "  sudo ln -sf /opt/apache-maven-${MAVEN_VERSION} /opt/maven"
        return 1
    fi

    # 下载（官方归档源，阿里云镜像已下架 3.9.6）
    local DOWNLOAD_URL="https://archive.apache.org/dist/maven/maven-3/${MAVEN_VERSION}/binaries/apache-maven-${MAVEN_VERSION}-bin.tar.gz"
    local FALLBACK_URL="https://dlcdn.apache.org/maven/maven-3/${MAVEN_VERSION}/binaries/apache-maven-${MAVEN_VERSION}-bin.tar.gz"

    log_info "从 Apache 归档源下载 Maven..."
    if ! wget -q "$DOWNLOAD_URL" -O /tmp/maven.tar.gz 2>/dev/null; then
        log_warn "阿里云源不可用，尝试官方源..."
        if ! wget -q "$FALLBACK_URL" -O /tmp/maven.tar.gz 2>/dev/null; then
            log_error "Maven 下载失败"
            return 1
        fi
    fi

    # 安装
    tar -xzf /tmp/maven.tar.gz -C /opt/
    ln -sf /opt/apache-maven-${MAVEN_VERSION} /opt/maven
    rm -f /tmp/maven.tar.gz

    # 设置环境变量
    cat > /etc/profile.d/maven.sh << 'EOF'
export MAVEN_HOME=/opt/maven
export PATH=$MAVEN_HOME/bin:$PATH
EOF
    source /etc/profile.d/maven.sh 2>/dev/null || true

    # 配置阿里云仓库镜像（写入实际用户的 ~/.m2，而非 root）
    local M2_DIR="${REAL_HOME}/.m2"
    mkdir -p "$M2_DIR"
    if [ ! -f "$M2_DIR/settings.xml" ]; then
        cat > "$M2_DIR/settings.xml" << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<settings>
    <mirrors>
        <mirror>
            <id>aliyun-central</id>
            <mirrorOf>central</mirrorOf>
            <name>阿里云 Maven 中央仓库</name>
            <url>https://maven.aliyun.com/repository/central</url>
        </mirror>
        <mirror>
            <id>aliyun-public</id>
            <mirrorOf>*</mirrorOf>
            <name>阿里云 Maven 公共仓库</name>
            <url>https://maven.aliyun.com/repository/public</url>
        </mirror>
    </mirrors>
</settings>
XMLEOF
        log_info "Maven settings.xml 已配置阿里云仓库（${REAL_HOME}/.m2/）"
    fi

    # 确保目录归属正确
    chown -R "$REAL_USER" "$M2_DIR" 2>/dev/null || true

    log_ok "Maven ${MAVEN_VERSION} 安装成功"
    return 0
}

# ============================================================
# 检查 Node.js
# ============================================================
check_node() {
    log_info "检查 Node.js..."

    if command -v node &> /dev/null; then
        NODE_VER=$(node -v 2>/dev/null | sed 's/^v//')
        NODE_MAJOR=$(echo "$NODE_VER" | cut -d'.' -f1)
        if [ "$NODE_MAJOR" -ge "$REQUIRED_NODE_MAJOR" ] 2>/dev/null; then
            log_ok "Node.js v${NODE_VER} 已安装（满足 >= $REQUIRED_NODE_MAJOR 要求）"
            # 同时检查 npm
            if command -v npm &> /dev/null; then
                log_ok "npm $(npm -v 2>/dev/null) 已安装"
            else
                log_warn "未检测到 npm 命令"
                NEED_INSTALL_NODE=true
                return 1
            fi
            return 0
        else
            log_warn "Node.js 版本 v${NODE_VER} 不满足要求（需要 >= $REQUIRED_NODE_MAJOR）"
        fi
    else
        log_warn "未检测到 node 命令"
    fi

    NEED_INSTALL_NODE=true
    return 1
}

# ============================================================
# 安装 Node.js 20（npmmirror 源加速）
# ============================================================
install_node() {
    log_info "开始安装 Node.js ${NODE_MAJOR_VERSION}..."

    # 检查 root 权限
    if [ "$EUID" -ne 0 ]; then
        log_error "安装 Node.js 需要 root 权限，请使用 sudo 运行"
        log_info "手动安装命令："
        echo "  curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR_VERSION}.x | sudo -E bash -"
        echo "  sudo apt-get install -y nodejs"
        return 1
    fi

    # 检测系统
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_ID=$ID
    else
        log_error "无法检测操作系统版本"
        return 1
    fi

    # 使用 NodeSource 安装（国内可通过 npmmirror 加速 npm）
    log_info "从 NodeSource 安装 Node.js ${NODE_MAJOR_VERSION}..."
    if curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR_VERSION}.x" | bash -; then
        if apt-get install -y -qq nodejs; then
            # 配置 npm 使用 npmmirror 源（国内加速，写入实际用户配置）
            su - "$REAL_USER" -c "npm config set registry https://registry.npmmirror.com" 2>/dev/null || npm config set registry https://registry.npmmirror.com 2>/dev/null || true

            # 安装 pnpm（可选但推荐）
            npm install -g pnpm 2>/dev/null || true

            log_ok "Node.js $(node -v) + npm $(npm -v) 安装成功"
            log_ok "npm 已配置 npmmirror 国内源"
            return 0
        fi
    fi

    # 回退方案：使用 APT 默认源的 nodejs（版本可能较旧）
    log_warn "NodeSource 不可用，尝试 APT 默认源..."
    apt-get update -qq
    if apt-get install -y -qq nodejs npm; then
        npm config set registry https://registry.npmmirror.com 2>/dev/null || true
        log_ok "Node.js $(node -v) + npm $(npm -v) 安装成功（APT 默认源）"
        return 0
    fi

    log_error "Node.js 安装失败"
    return 1
}

# ============================================================
# 主流程
# ============================================================
echo ""
echo "============================================================"
echo "  开发环境工具检查"
echo "  要求：JDK >= $REQUIRED_JDK_MAJOR, Maven >= $REQUIRED_MAVEN_MAJOR, Node.js >= $REQUIRED_NODE_MAJOR"
echo "============================================================"
echo ""

# 检查阶段
check_jdk || true
check_maven || true
check_node || true

# 安装阶段
if [ "$NEED_INSTALL_JDK" = true ] || [ "$NEED_INSTALL_MAVEN" = true ] || [ "$NEED_INSTALL_NODE" = true ]; then
    echo ""
    log_info "检测到缺失组件，开始自动安装..."
    echo ""

    if [ "$NEED_INSTALL_JDK" = true ]; then
        install_jdk || log_warn "JDK 安装失败，请手动安装"
    fi

    if [ "$NEED_INSTALL_MAVEN" = true ]; then
        install_maven || log_warn "Maven 安装失败，请手动安装"
    fi

    if [ "$NEED_INSTALL_NODE" = true ]; then
        install_node || log_warn "Node.js 安装失败，请手动安装"
    fi

    # 验证安装结果
    echo ""
    log_info "验证安装结果..."
    if command -v java &> /dev/null; then
        log_ok "java: $(java -version 2>&1 | head -1)"
    else
        log_error "java 仍不可用，请手动检查 PATH"
    fi
    if command -v mvn &> /dev/null; then
        log_ok "mvn: $(mvn -version 2>&1 | head -1)"
    else
        log_error "mvn 仍不可用，请手动检查 PATH"
    fi
    if command -v node &> /dev/null; then
        log_ok "node: $(node -v 2>/dev/null)"
    else
        log_error "node 仍不可用，请手动检查 PATH"
    fi
    if command -v npm &> /dev/null; then
        log_ok "npm: $(npm -v 2>/dev/null)"
    else
        log_error "npm 仍不可用，请手动检查 PATH"
    fi
else
    echo ""
    log_ok "所有开发工具已就绪，无需安装"
fi

echo ""
echo "============================================================"
