#!/bin/bash

# 顏色定義
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}===================================${NC}"
echo -e "${CYAN}       自動 Git 提交推送腳本       ${NC}"
echo -e "${CYAN}===================================${NC}"
echo ""

# 確保在有變更的狀態
CHANGES=$(git status -s)
if [ -z "$CHANGES" ]; then
    echo -e "${YELLOW}目前沒有發現被修改或新增的檔案，不需執行。${NC}"
    exit 0
fi

echo -e "目前發現以下變更："
git status -s
echo ""

# 加入暫存區
echo -e "${YELLOW}正在將所有變更加入暫存區 (git add .)...${NC}"
git add .
echo -e "${GREEN}完成。${NC}"
echo ""

# 檢查是否真的有 staged 變更
if git diff --staged --quiet; then
    echo -e "${YELLOW}沒有內容可供 Commit，即將退出。${NC}"
    exit 0
fi

COMMIT_MSG=""

# 詢問模式
echo -e "請問您要如何產生 Commit 訊息？"
echo "  1) 系統自動產生 (AI)"
echo "  2) 自行輸入"
read -p "請選擇 [1/2] (預設為 1): " CHOICE
CHOICE=${CHOICE:-1}

if [ "$CHOICE" == "1" ]; then
    echo -e "${YELLOW}正在請 AI 分析程式碼變更並產生 Commit 訊息，請稍候...${NC}"
    
    # 使用 venv 執行 python，並接管 stdout 進入變數
    # 隱藏 stderr (或是讓它印出但不影響 $COMMIT_MSG)，因為我們只想要訊息本體
    # 但如果在 Windows/Git Bash 下路徑可能是 venv/Scripts/python 或 venv/bin/python
    if [ -f "venv/Scripts/python.exe" ]; then
        PY_CMD="venv/Scripts/python.exe"
    elif [ -f "venv/bin/python" ]; then
        PY_CMD="venv/bin/python"
    else
        PY_CMD="python"
    fi

    echo -e "${YELLOW}AI分析中，請稍候...${NC}"
    # 把 stderr 重定向回 stdout 或印出，方便除錯
    COMMIT_MSG=$($PY_CMD scripts/auto_commit.py 2>&1)
    EXIT_CODE=$?

    if [ $EXIT_CODE -ne 0 ] || [ -z "$COMMIT_MSG" ]; then
        echo -e "${RED}AI 產生訊息失敗。底下為錯誤附魔/回傳：${NC}"
        echo "$COMMIT_MSG"
        echo -e "${RED}請改為手動輸入。${NC}"
        read -p "請手動輸入 Commit 訊息: " COMMIT_MSG
    else
        echo -e "${CYAN}===================================${NC}"
        echo -e "${GREEN}$COMMIT_MSG${NC}"
        echo -e "${CYAN}===================================${NC}"
        
        read -p "是否使用以上訊息提交？ (y/n/e) [y=確認, n=重寫, e=編輯] (預設 y): " CONFIRM
        CONFIRM=${CONFIRM:-y}
        
        if [ "$CONFIRM" == "n" ] || [ "$CONFIRM" == "N" ]; then
            read -p "請重新手動輸入 Commit 訊息: " COMMIT_MSG
        elif [ "$CONFIRM" == "e" ] || [ "$CONFIRM" == "E" ]; then
            read -e -p "請編輯訊息: " -i "$COMMIT_MSG" COMMIT_MSG
        fi
    fi
else
    read -p "請輸入 Commit 訊息 (繁體中文): " COMMIT_MSG
fi

# 在經過各種選擇後，如果訊息仍為空則退出
if [ -z "$COMMIT_MSG" ]; then
    echo -e "${RED}Commit 訊息不能為空，已取消整個流程。${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}正在提交...${NC}"
git commit -m "$COMMIT_MSG"
echo -e "${GREEN}Commit 完成。${NC}"
echo ""

# 詢問是否要 push
read -p "是否要立即推送到遠端儲存庫？ (y/n) (預設 y): " DO_PUSH
DO_PUSH=${DO_PUSH:-y}

if [ "$DO_PUSH" == "y" ] || [ "$DO_PUSH" == "Y" ]; then
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    echo -e "${YELLOW}正在推送到 origin/$BRANCH ...${NC}"
    git push origin "$BRANCH"
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}推送完成！🎉${NC}"
    else
        echo -e "${RED}推送時發生錯誤，請檢查您的網路或遠端狀態。${NC}"
    fi
else
    echo -e "${CYAN}變更已保留在本地 (未推送到遠端)。${NC}"
fi

exit 0
