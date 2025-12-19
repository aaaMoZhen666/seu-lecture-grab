import json
import sys
import time
import os
from datetime import datetime, timedelta

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from playwright.sync_api import sync_playwright

lecture_data = {
    'headers': {
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate',
        'Accept-Language': 'zh-CN,zh;q=0.9,zh-TW;q=0.8,en-US;q=0.7,en;q=0.6',
        'Connection': 'keep-alive',
        'Content-Length': '0',
        'Host': 'ehall.seu.edu.cn',
        'Origin': 'http://ehall.seu.edu.cn',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
        'Referer': 'https://ehall.seu.edu.cn/gsapp/sys/jzxxtjapp/*default/index.do',
        'X-Requested-With': 'XMLHttpRequest',
        'Cookie': '',
    },
    'activity_list': [],
    'vcode_base64': '',
    'vcode': '',
}

session = requests.Session()


def load_personal_config():
    """加载个人配置文件"""
    with open('./config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config


def get_cookie_auto(login_id, login_pwd):
    """
    通过访问讲座相关页面会跳转到登录界面来获取 Cookie
    Tips:
    1.第一次使用可能遇到要输入短信验证码的情况，手速不够请将 timeout=10000 改为 timeout=60000 或更长时间
    2.默认使用本地的谷歌浏览器，如有其他需求自行更改
    """
    CHROME_PATH = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
    PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'playwright_user_data')
    TARGET_URL = 'https://ehall.seu.edu.cn/gsapp/sys/jzxxtjapp/hdyy/queryActivityList.do'

    with sync_playwright() as p:
        try:
            # browser = p.chromium.launch(executable_path=CHROME_PATH, headless=False)
            # context = browser.new_context()
            context = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR, executable_path=CHROME_PATH, headless=False
            )

            page = context.new_page()
            page.goto(TARGET_URL)
            page.fill('input[placeholder="一卡通号/唯一ID"]', login_id)
            page.fill('input[placeholder="请输入密码"]', login_pwd)
            page.click('button.ant-btn.ant-btn-primary.login-button-pc')

            page.wait_for_url(lambda url: TARGET_URL in url, timeout=10000)
            cookies = context.cookies()
            lecture_data['headers']['Cookie'] = '; '.join([f'{c["name"]}={c["value"]}' for c in cookies])

            context.close()
            # browser.close()
        except Exception as e:
            print(f'[Cookie获取][失败]\n{e}')
            return False
        else:
            print('[Cookie获取][成功]')
            return True


def get_lecture_data():
    """获取所有讲座信息，只保留 WID、讲座名称、预约开始时间等关键信息"""
    try:
        page_index = 1
        page_size = 10

        while True:
            response = session.post(
                url='https://ehall.seu.edu.cn/gsapp/sys/jzxxtjapp/hdyy/queryActivityList.do',
                headers=lecture_data['headers'],
                data={'pageIndex': page_index, 'pageSize': page_size},
                timeout=5,
            )
            response.raise_for_status()
            data = response.json()

            records = data.get('datas', [])
            if not records:
                break

            for idx, lecture in enumerate(records, start=len(lecture_data['activity_list']) + 1):
                lecture_data['activity_list'].append(
                    {'ID': idx, 'WID': lecture['WID'], 'JZMC': lecture['JZMC'], 'YYKSSJ': lecture['YYKSSJ']}
                )

            if len(records) < page_size:
                break

            page_index += 1
    except (requests.RequestException, KeyError) as e:
        print(f'[讲座数据获取][失败]\n{e}')
        return False
    else:
        print('[讲座数据获取][成功]\n>>编号 - 讲座名称 - 预约开始时间')
        for lecture in lecture_data['activity_list']:
            print(f'>>{lecture["ID"]} - {lecture["JZMC"]} - {lecture["YYKSSJ"]}')
        return True


def get_verify_code_base64():
    """获取预约时验证码图片的 base64 编码"""
    try:
        response = session.get(
            url='https://ehall.seu.edu.cn/gsapp/sys/jzxxtjapp/hdyy/vcode.do',
            params={'_': int(time.time() * 1000)},
            headers=lecture_data['headers'],
            timeout=5,
        )
        response.raise_for_status()

        lecture_data['vcode_base64'] = response.json()['result'].replace('data:image/jpeg;base64,', '', 1)
    except (requests.RequestException, KeyError) as e:
        print(f'[验证码获取][失败]\n{e}')
        return False
    else:
        print('[验证码获取][成功]')
        return True


def parse_verify_code(parse_params):
    """使用超级鹰解析验证码"""
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
    }

    try:
        response = requests.post(
            url='https://upload.chaojiying.net/Upload/Processing.php', headers=HEADERS, data=parse_params
        )
        response.raise_for_status()

        response = response.json()
        if response['err_no'] == 0:
            lecture_data['vcode'] = response['pic_str']
        else:
            raise ValueError('请求参数错误')
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f'[验证码解析][失败]\n{e}')
        return False
    else:
        print('[验证码解析][成功]')
        return True


def reserve_lecture(wid, vcode):
    """预约指定讲座"""
    reserve_params = {'paramJson': json.dumps({'HD_WID': wid, 'vcode': vcode})}

    try:
        response = session.post(
            url='https://ehall.seu.edu.cn/gsapp/sys/jzxxtjapp/hdyy/yySave.do',
            data=reserve_params,
            headers=lecture_data['headers'],
            timeout=5,
        )

        response.raise_for_status()

        response = response.json()
        if response['code'] != 200:
            raise ValueError(response['msg'])
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f'[讲座预约][失败]\n{e}')
        return False
    else:
        print('[讲座预约][成功]')
        return True


def keep_alive():
    """通过访问讲座相关页面保活"""
    try:
        response = session.post(
            url='https://ehall.seu.edu.cn/gsapp/sys/jzxxtjapp/hdyy/queryActivityList.do',
            headers=lecture_data['headers'],
            timeout=5,
        )
        response.raise_for_status()
    except requests.RequestException:
        print('[状态保活][失败]')
        return False
    else:
        print('[状态保活][成功]')
        return True


def auto_task_recover_alive(config):
    """定时保活，失败时重新获取 Cookie"""
    if not keep_alive():
        get_cookie_auto(config['loginSEU']['id'], config['loginSEU']['pwd'])


def auto_task_rob_lecture(config, wid):
    """抢讲座"""
    MAX_ATTEMPTS = 10
    attempt = 0

    parse_params = dict(config['chaojiying'])

    while attempt < MAX_ATTEMPTS:
        print(f'[正在进行第{attempt + 1}次尝试]')
        attempt += 1
        if not get_verify_code_base64():
            continue

        parse_params['file_base64'] = lecture_data['vcode_base64']

        if not parse_verify_code(parse_params):
            continue

        if reserve_lecture(wid, lecture_data['vcode']):
            break
        else:
            time.sleep(0.05)

    scheduler.shutdown(wait=False)


if __name__ == '__main__':
    print('[开始]')

    config = load_personal_config()

    if not get_cookie_auto(config['loginSEU']['id'], config['loginSEU']['pwd']):
        sys.exit()

    if not get_lecture_data():
        sys.exit()

    print('[输入]')
    id = int(input('请输入目标讲座编号：'))
    target = lecture_data['activity_list'][id - 1]
    print(f'[已选目标]\n{target["ID"]} - {target["JZMC"]} - {target["YYKSSJ"]}')

    # 测试用
    # target['YYKSSJ'] = '2025-12-19 00:18:00'

    end_recover_alive_date = datetime.strptime(target['YYKSSJ'], '%Y-%m-%d %H:%M:%S') - timedelta(seconds=0)
    start_rob_lecture_date = datetime.strptime(target['YYKSSJ'], '%Y-%m-%d %H:%M:%S') - timedelta(seconds=0.5)

    print(f'[定时任务启动]\n何时停止保活：{end_recover_alive_date} 何时开始抢：{start_rob_lecture_date}')

    # 测试用
    # get_verify_code_base64()
    # parse_params = config['chaojiying']
    # parse_params['file_base64'] = lecture_data['vcode_base64']
    # parse_verify_code(parse_params)
    # print(lecture_data)
    # reserve_lecture(target['WID'], lecture_data['vcode'])

    scheduler = BlockingScheduler()
    scheduler.add_job(auto_task_recover_alive, 'interval', seconds=30, end_date=end_recover_alive_date, args=[config])
    scheduler.add_job(auto_task_rob_lecture, 'date', run_date=start_rob_lecture_date, args=[config, target['WID']])
    scheduler.start()
