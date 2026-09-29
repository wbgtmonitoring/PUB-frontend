python3 -c "import ast; ast.parse(open('/data/render/tg323_station_monitor.py').read()); print('SYNTAX OK')"

python3 /data/render/tg323_station_monitor.py

```
Expected output:
============================================================
  KNF  -  Station Monitor (TG323)
============================================================

  Station:     KNF-B452BF260717021
  Status:      ONLINE
  Last update: 24/09/2026, 18:XX:XX SGT
  Age:         45s ago

+-- Latest Values --------------------------------------+
  Blackglobe Temp         25.2 C
  Rel Humidity            52.6 %
  Air Temp                25.7 C
  WBGT                   20.88 C
  Battery                12.16 V
+-------------------------------------------------------+

  Refreshing every 60s. Ctrl+C to exit.
```


cat > /etc/resolv.conf << 'EOF'
nameserver 8.8.8.8
nameserver 1.1.1.1
EOF

cat /etc/resolv.conf