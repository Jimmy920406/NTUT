# 預設有docker wsl2
# <>這個符號是可以修改的變數，輸入時不需要<>
---
## 建立docker 映像檔
- 先建立一個資料夾
- 用記事本創建Dockerfile
```Dockerfile
# 使用 PyTorch 官方 GPU 映像檔作為基底 (內建 CUDA)
FROM pytorch/pytorch:latest

# 安裝 SSH 伺服器與常用工具
RUN apt-get update && apt-get install -y openssh-server sudo nano

# 在這裡加入你想幫大家預先裝好的 Python 套件！
RUN pip install <pandas> <numpy> <scikit-learn> <matplotlib> <jupyter>

# 設定 SSH 運作所需的目錄
RUN mkdir -p /var/run/sshd

# 建立一個新使用者 (帳號: devuser, 密碼: devuser)
RUN useradd -rm -d /home/<devuser> -s /bin/bash -g root -G sudo -u 1000 <devuser>
RUN echo '<devuser>:<devuser>' | chpasswd

# 先用 root 權限安裝所有需要的套件
USER root

# 1. 一次安裝 tmux, zsh, git, curl, 還有之前漏掉的 Python venv
RUN apt-get update && apt-get install -y \
    tmux \
    zsh \
    git \
    curl \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# 2. 直接把 devuser 的預設 Shell 綁定為 Zsh (一步到位)
RUN chsh -s /usr/bin/zsh <devuser>

# ------------------------------------------
# 切換到 devuser 身份，這樣產生的設定檔擁有者才會是他，不會被鎖權限
USER <devuser>
WORKDIR /home/<devuser>

# 3. 寫入 tmux 設定檔 (讓他一打開就有 256 色，並且預設使用 Zsh)
RUN echo 'set -g default-terminal "screen-256color"' > ~/.tmux.conf && \
    echo 'set-option -g default-shell /usr/bin/zsh' >> ~/.tmux.conf

# 4. 全自動安裝 Oh My Zsh (注意最後面的 --unattended 參數，這是 Docker 專用的「不卡住」大絕招)
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended

# 5. 下載「自動預測」與「語法高亮」雙砲管外掛
RUN git clone https://github.com/zsh-users/zsh-autosuggestions ~/.oh-my-zsh/custom/plugins/zsh-autosuggestions && \
    git clone https://github.com/zsh-users/zsh-syntax-highlighting.git ~/.oh-my-zsh/custom/plugins/zsh-syntax-highlighting

# 6. 使用 sed 指令，全自動把 plugins=(git) 替換成包含雙外掛的版本
RUN sed -i 's/plugins=(git)/plugins=(git zsh-autosuggestions zsh-syntax-highlighting)/g' ~/.zshrc

# ------------------------------------------
# (重要) 最後記得切回 root，因為啟動 SSH 服務通常需要 root 權限
USER root

# 確保允許密碼登入
RUN sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config

# 開放 22 Port
EXPOSE 22

# 啟動 SSH 服務
CMD ["/usr/sbin/sshd", "-D"]
```
- useradd 是建立統一的使用者，後續拓展22端口時，會再分配不同人的名稱
- 下面那行是設定devuser的密碼
- 檔名輸入:"Dockerfile"，前後一定要加雙引號，這樣才不會被存成 Dockerfile.txt）
- 在cmd中cd進入資料夾，輸入下面的指令建立映像檔
```DOS
docker build -t <gpu_ssh_image> .
```
- 建立gpu_ssh_image這個映像檔
- 等待下載
---
## 擴展22端口給其他人使用
```DOS
docker run -d --name <user_a_env> --hostname <user_a_env> --gpus all -p 2201:22 gpu_ssh_image
docker exec -it <user_a_env> passwd <devuser>
docker update --cpus="<4.0>" --memory="<8g>" --memory-swap="<8g>" <user_a_env>
```
- 2201就是拓展的1號端口，如果有第二個人就是2202，以此類推
- user_a_env是容器名稱
- hostname是當使用者進入容器時原本會看到:devuser@ad4155fb4d91:~$，會變成:devuser@user_a_env:~$
    - 亂碼其實是這個容器的 「真實身分證字號 (Container ID)」
- 第二條指令是修改密碼
- 系統會提示你輸入兩次新密碼
- user_a_env是容器，devuser是帳號，所以密碼是容器裡的使用者密碼
- 第三條指令是限制資源:
    - cpus:核心數量
    - memory:記憶體
    - memory-swap:將 Swap (虛擬記憶體) 設為跟 RAM 一樣大，這是為了防止容器偷偷吃掉你 Windows 系統硬碟的空間。如果不設定，預設 Swap 會是 RAM 的兩倍
- gpus all是把GPU算力全部借給容器，因為使用消費級顯卡，所以無法分配部分算力，只能使用者自行限制(君子條款)
```Python
import torch
# 限制只能使用第 0 張顯卡的 50% 記憶體
torch.cuda.set_per_process_memory_fraction(0.5, 0)
```
- 如果有多張顯卡可以指定特定顯卡給特定的人
```DOS
docker run -d --name <user_a_env> --gpus '"device=0"' -p 2201:22 gpu_ssh_image
```
---
## local端測試(localhost)
- 開啟vscode
- 安裝 Remote-ssh擴充套件
- Ctrl+Shift+P 輸入ssh選擇Remote-SSH: Open SSH Configuration File...
- 選擇第一個設定檔(通常在 C:\Users\你的帳號\.ssh\config)
```
Host Local_GPU_Test
    HostName localhost       # 因為是同一台電腦，直接填 localhost 即可
    User <devuser>             # 我們在 Dockerfile 裡設定的帳號
    Port 2201                # 對應你開給這個容器的 Port
```
- 點擊左下角><標誌
- 選擇Connect to Host
- 選Local_GPU_Test
- VS Code 會開一個新視窗。如果它問你作業系統類型，請選擇 Linux（因為 Docker 裡面跑的是 Linux 環境）。
- 選擇Continue
- 輸入密碼 <devuser>
---
## Tailscale
### Host端
- 安裝Tailscale
- 進入Machines找到設備(https://login.tailscale.com/admin/machines)
- 設備右邊有三個小點，選擇Share...
- 輸入其他人的email，或是分享Invite Link
- 設備上的xxx.xxx.xxx.xx就是IP
### client端
- 安裝Tailscale
- 接受邀請
- 開啟vscode
- 安裝 Remote-SSH(Extensions)
- 點擊左下角><
- 選擇Connect to Host
- 選擇Add New SSH Host
- 輸入下面指令
```Bash
ssh -p <2201> <devuser>@<xxx.xxx.xxx.xx>
```
- 分別是host給你的端口，host的帳號名稱(不是你的容器名)，IP
- 接著它會問你要把設定檔存在哪裡，直接選第一個預設路徑（通常是 C:\Users\你的名字\.ssh\config）就好。
- 右下角會跳出通知說新增成功，點擊 「Connect (連線)」
- vscode跳新視窗，選擇Linux(因為伺服器內部是 Linux 環境)
- 選擇Continue
- 輸入你容器的密碼
- 當你看到左下角的綠色圖示變成 SSH: xxx.xxx.xxx.xx，恭喜你
- 點擊Open Folder，預設/home/<devuser>(有時會需要再輸入一次密碼確認)
- Open Folder也可以開你新增的資料夾(然後一樣輸入密碼)
---
## fileZilla
- Gui的傳送檔案介面
- 本指南最下方有常用指令，其中有傳送檔案的指令，如果比較喜歡GUI介面，可以看這個段落
- 下載fileZilla
- 主機:sftp://xxx.xxx.xxx.xx
- 使用者名稱:<devuser>
- port:<2201>
- 密碼:你容器的密碼
- 按下快速連線就可以用了
---
## 容器轉成映像檔

```DOS
docker commit <user_a_env> <my_custom_gpu_image>
```
- 假設你剛剛是在 user_a_env 這個容器裡面安裝套件的，你想把它存檔並命名為 my_custom_gpu_image 映像檔
```DOS
docker run -d --name <user_c_env> --gpus all -p 2203:22 <my_custom_gpu_image>
```
- 把剛剛建立的映像檔給user_c_env這個容器
---
## 個人環境優化
### venv:
```Bash
sudo apt update
```
- 更新 Linux 的軟體源清單
```Bash
sudo apt install python3.10-venv -y
```
- 字尾的 -y 是讓它自動同意安裝，不用再按 Y 確認。
```Bash
python3 -m venv <.venv>
```
- 建立環境
```Bash
source .venv/bin/activate
```
- 啟動環境
### tmux
- 關了電腦終端能繼續跑(tmux會在伺服器內部開一個「永遠不死的背景終端機」)
- 這個我有放到Dockerfile裡面，所以預設就有，如果沒有就往下看
```Bash
sudo apt update
sudo apt install tmux -y
```
- 下載
```Bash
tmux new -s <training>
```
- 建立tmux空間，空間名稱為training
- 最下方會出現一條綠色的狀態列，代表你現在已經身處在 tmux
- 如何讓你的程式能關機持續運行:
    - 按下Ctrl+B
    - 按D(代表Detach)
    - 你會瞬間被彈回原本正常的終端機畫面，並看到提示寫著 [detached (from session training)]。這時候你就可以安心把 VS Code 關掉了，裡面的程式絕對不會死！
```Bash
tmux attach -t <training>
```
- 重新接上空間(attach)
- 如果忘記有哪些空間:
```Bash
tmux ls
```
### zsh
- 能夠記得你打過的指令
- 讓版面變好看(配色等等)
- Dockerfile預設也有，如果沒有往下看
```Bash
sudo apt update
sudo apt install zsh git curl -y
```
```Bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
```
- 黑白介面，換成超級漂亮且支援外掛的主題
- 跑到一半時，它可能會問你 "Do you want to change your default shell to zsh? [Y/n]"，請輸入 Y 然後按 Enter
- 成功後，你會看到畫面出現一個大大的彩色的 OH MY ZSH 字樣
```Bash
git clone https://github.com/zsh-users/zsh-autosuggestions ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-autosuggestions
```
- 預測你曾經打過的指令的外掛
```Bash
code ~/.zshrc
```
- 打開設定檔，找到plugins=(git)，改成 plugins=(git zsh-autosuggestions zsh-syntax-highlighting)，存檔
```Bash
source ~/.zshrc
```
- 讓設定生效
```Bash
code ~/.tmux.conf
```
- 開啟設定檔
- 把 /bin/bash改成/usr/bin/zsh，存檔
--- 
## 其他常用指令
### docker相關
```DOS
docker ps
```
- 列出正在運作的容器和被使用的端口

```DOS
docker stop <user_a_env>
docker start <user_a_env>
```
- 暫停/開啟 容器(暫時關閉/開啟 端口)

```DOS
docker stop <user_a_env>
docker rm <user_a_env>
```
- 先暫停容器，然後永久刪除

```DOS
docker rename <舊名稱> <新名稱>
```
- 改容器名
- 容器還在運行的時候直接改名，完全不會影響裡面正在跑的程式
### 傳檔案
```Bash
rsync -avz -e "ssh -p <2201>" <./> <devuser@IP:/home/devuser/>
```
- ./是你的檔案位置
- 後面是你要放的位置
---


