#!/usr/bin/python3.6
# -*- coding: utf-8 -*-
import logging
import sys
import os
from os.path import join, dirname
from flask import Flask, request, abort, send_file
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    CarouselColumn, CarouselTemplate, URITemplateAction, TemplateSendMessage, MessageEvent, TextMessage, LocationMessage, LocationSendMessage,TextSendMessage, StickerSendMessage, MessageImagemapAction, ImagemapArea, ImagemapSendMessage, BaseSize
)
from io import BytesIO, StringIO
from PIL import Image, ImageFile
import requests
import urllib.parse
import math
import sqlalchemy
from dotenv import load_dotenv

load_dotenv(verbose=True)
dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

LINE_BOT_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_BOT_CHANNEL_ACCESS_TOKEN')
LINE_BOT_CHANNEL_SECRET = os.environ.get('LINE_BOT_CHANNEL_SECRET')
GOOGLE_MAPS_STATIC_API_KEY = os.environ.get('GOOGLE_MAPS_STATIC_API_KEY')
MYSQL_CONNECTION_NAME = os.environ.get('MYSQL_CONNECTION_NAME')
MYSQL_USER = os.environ.get('MYSQL_USER')
MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD')
MYSQL_DATABASE = os.environ.get('MYSQL_DATABASE')
MAX_WIFI_NUM = os.environ.get('MAX_WIFI_NUM')

app = Flask(__name__)

line_bot_api = LineBotApi(LINE_BOT_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_BOT_CHANNEL_SECRET)

@app.route("/", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']

    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    line_bot_api.reply_message(
        event.reply_token,
        [
            TextSendMessage(text='下のボタンから位置情報を送ってね')
        ]
    )

'''
@app.route("/imagemap/<path:url>/<size>")
def imagemap(url, size):
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    map_image_url = urllib.parse.unquote(url)
    response = requests.get(map_image_url)
    img = Image.open(BytesIO(response.content))
    img_resize = img.resize((int(size), int(size)))
    byte_io = BytesIO()
    img_resize.save(byte_io, 'PNG')
    byte_io.seek(0)
    return send_file(byte_io, mimetype='image/png')
'''
@app.route("/imagemap/<path:url>/<size>")
def imagemap(url, size):
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    byte_io = BytesIO()
    map_image_url = urllib.parse.unquote(url)
    response = requests.get(map_image_url)
    img = Image.open(BytesIO(response.content))
    img_resize = img.resize((int(size), int(size)))
    img_resize.save(byte_io, 'PNG')
    byte_io.seek(0)
    
    return send_file(byte_io, mimetype='image/png')

@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    lat = event.message.latitude
    lon = event.message.longitude

    # データベース
    db = sqlalchemy.create_engine(
        sqlalchemy.engine.url.URL(
            drivername='mysql+pymysql',
            username=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            query={
                'unix_socket': '/cloudsql/{}'.format(MYSQL_CONNECTION_NAME)
            }
        ),
    )

    select_sql = 'SELECT id, name, address, detail_address_info, latitude, longitude, ssid, url, '
    select_sql += 'GLENGTH(GEOMFROMTEXT(CONCAT(\'LINESTRING({} {},\',longitude,\' \',latitude,\')\'))) AS distance '.format(lon, lat)
    select_sql += 'FROM free_wifi '
    select_sql += 'ORDER BY distance '
    select_sql += 'LIMIT {}'.format(MAX_WIFI_NUM)
   
    response_json_list = []
    wifi_markers_url = ''
    max_km = 0.0
    
    with db.connect() as conn:
        recent_votes = conn.execute(select_sql).fetchall()
        
        for row in recent_votes:
            map_id = len(response_json_list) + 1
            id = int(row[0])
            name = row[1]
            address = row[2]
            detail_address_info = row[3]
            latitude = float(row[4])
            longitude = float(row[5])
            ssid = row[6]
            url = row[7]
            distance = float(row[8])
            km_per_degree = 40075.0 / 360.0
            km = distance * km_per_degree
            m = math.floor(km * 1000)
            max_km = km
            title = str(map_id) + '：' + name

            if len(title) > 40:
                title = title[:37] + '...'
                
            result = {
                "title": title,
                "text": '指定位置から{}m\nSSID：{}'.format(m, ssid),
                "action1": {"type": 'uri', "label": 'Googleマップで開く', "uri": 'https://www.google.com/maps/search/?api=1&query={},{}'.format(str(latitude), str(longitude))},
                "action2": {"type": 'uri', "label": 'Wi-Fi提供元HP', "uri": url } 
            }

            response_json_list.append(result)

            wifi_markers_url += '&markers=color:red|label:{}|{},{}'.format(map_id, latitude, longitude)

    zoom = 7.0
    limit_km = 100.0
  
    while limit_km > max_km:
        zoom += 1
        limit_km /= 2

    map_image_url = 'https://maps.googleapis.com/maps/api/staticmap?center={},{}&zoom={}&size=520x520&scale=2&maptype=roadmap&key={}'.format(lat, lon, zoom, GOOGLE_MAPS_STATIC_API_KEY)
    map_image_url += '&markers=color:blue|label:|{},{}'.format(lat, lon)
    map_image_url += wifi_markers_url
  
    imagesize = 1040

    columns = [
        CarouselColumn(
            title=column["title"],
            text=column["text"],
            actions=[
                URITemplateAction(
                    label=column["action1"]["label"],
                    uri=column["action1"]["uri"],
                ),
                URITemplateAction(
                    label=column["action2"]["label"],
                    uri=column["action2"]["uri"],
                )
            ]
        )
        for column in response_json_list
    ]

    messages = [
        ImagemapSendMessage(
            base_url = 'https://{}/imagemap/{}'.format(request.host, urllib.parse.quote_plus(map_image_url)),
            alt_text = '地図',
            base_size = BaseSize(height=imagesize, width=imagesize),
            actions = []
        ),
        TemplateSendMessage(
            alt_text="近くのWi-Fi情報",
            template=CarouselTemplate(columns=columns),
        )
    ]

    line_bot_api.reply_message(
        event.reply_token,
        messages=messages
    )

if __name__ == "__main__":
    app.run()
