
This instructions are for Windows users only

# PUB connecting to TG452 and Render


## Overview of the repository
```
PUB_TG452_repo
│   app.py
│   auth.py
│   db.py
│   readme.md
│   render.yaml
│   requirements.txt
│   
├───device
│   │   tg323_puller.py
│   │   tg452_pusher.py
│   │   
│   └───__pycache__
│           tg323_puller.cpython-312.pyc
│           tg452_pusher.cpython-312.pyc
│           
├───static
│       pub_logo.png
│       pub_web.css
│       pub_web.html
│       pub_web.js
│       
├───TG452_PUB_backup_settings
│       backup-router-2026-09-23.tar.gz
│       
└───__pycache__
        app.cpython-312.pyc
        auth.cpython-312.pyc
        db.cpython-312.pyc
```

## Instructions on how to clone and run multiple devices at same time


1. clone the repository: https://github.com/WetecPteLtd/pub-heatstress-tg452-client onto your local computer.

2. Go to the Bivocom TG452 and use serial communicatino connect the device from the TG452 to your computer device and SSH it or serial connect to the device [You may use things like PUTTY].

3. Under data create a folder called "pub-tg452-client": mkdir pub-tg452-client

4. In your computer device go to Powershell (admin mode) and type in the following command after once you have clone into your computer, go to that folder path that you have cloen it at and type:

```
scp -O "-oKexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1" "-oHostKeyAlgorithms=+ssh-rsa,ssh-dss" "-oMACs=+hmac-sha1,hmac-md5" main.py requirements.txt .env admin@192.168.1.1:/data/pub-tg452-client/
```
5. Now, go to your TG452:
```
cd /data/pub-tg452-client
```
6. Once inside the folder type the following to check if the files exsist:
```
# Type in this
ls -la

# Expected result
drwxr-xr-x    2 admin    root           368 Sep 23 13:58 .
drwxr-xr-x    5 admin    root           456 Sep 23 14:07 ..
-rw-r--r--    1 admin    root           229 Sep 23 14:55 .env
-rw-r--r--    1 admin    root         10178 Sep 23 13:58 main.py
-rw-r--r--    1 admin    root            13 Sep 23 13:58 requirements.txt
```

7. Make sure to edit the .env file to your respective device that you want to connect, make sure is the same as the Database (DB)
```
# Type this:
vim .env

# To write in vim press 'i' or 'I'

# Change only the DEVICE_ID

#Expected result
DEVICE_ID=UPWRP-B452BF260731003^M
CSV_DIR=./output^M
TMP_DIR=/tmp/pub-heatstress-tg452-client^M
LOG_INTERVAL_S=60^M
TX_INTERVAL_S=60^M
RENDER_API_URL=https://pub-frontend.onrender.com/api/readings^M
API_TOKEN=pub-tg452-secret-2026-xYz9

# To Save the things that you have written ':wq' then press enter

# To check on the .env file: 'cat .env'

DEVICE_ID=UPWRP-B452BF260731003
CSV_DIR=./output
TMP_DIR=/tmp/pub-heatstress-tg452-client
LOG_INTERVAL_S=60
TX_INTERVAL_S=60
RENDER_API_URL=https://pub-frontend.onrender.com/api/readings
```

8. To install the python packages:
```
# First
pip3 install --target=/data/python_packages python-dotenv requests "urllib3<2"

# Second
pip3 install --target=/data/python_packages pyserial
```

9. Write the init script to run in the background of your TG452 as long it is powered on
```
cat > /etc/init.d/tg452-client << 'EOF'
#!/bin/sh /etc/rc.common
START=99
STOP=10
USE_PROCD=1

start_service() {
    procd_open_instance
    procd_set_param command /usr/bin/python3 /data/pub-tg452-client/main.py
    procd_set_param env PYTHONPATH=/data/python_packages
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_set_param respawn 3600 5 5
    procd_set_param term_timeout 10
    procd_close_instance
}

stop_service() {
    killall -9 -f "/data/pub-tg452-client/main.py" 2>/dev/null
    sleep 1
}
EOF
```

10. Make the init script executable
```
chmod 755 /etc/init.d/tg452-client
ls -la /etc/init.d/tg452-client

# Expected result
-rwxr-xr-x  1 admin  root  ...  /etc/init.d/tg452-client
```

11. To start and Enable your script to run in the background
```
/etc/init.d/tg452-client enable
/etc/init.d/tg452-client start
sleep 3
ps | grep main.py | grep -v grep
```

12. Now we need to verify and check logs on Render
```
tail -n 10 /data/pub-tg452-client/logs/system.log
curl -s https://pub-frontend.onrender.com/api/devices
```

