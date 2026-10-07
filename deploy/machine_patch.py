"""Narrow machine-monitor integration on top of the verified runtime."""
def once(text,before,after):
    if text.count(before)!=1:raise ValueError('machine patch anchor mismatch: '+before[:100])
    return text.replace(before,after,1)

def patch_service(source):
    text=source.decode().replace('\r\n','\n')
    return once(text,'    @contextlib.contextmanager\n    def db', '        from .machines import Machines\n        self.machines = Machines(self)\n\n    @contextlib.contextmanager\n    def db').encode()

def patch_server(source):
    text=source.decode().replace('\r\n','\n')
    routes='''            machine_page=re.fullmatch(r'/v1/dashboard/([A-Za-z0-9_-]{43})/machines(?:/([0-9a-f]{32}))?',route)
            if machine_page:
                manager=self.server.store.machines
                if self.command=='GET' and not machine_page.group(2):return self.reply(200,{'machines':manager.list(machine_page.group(1))})
                if self.command=='POST' and not machine_page.group(2):
                    result=manager.create(machine_page.group(1),data)
                    config={'url':self.server.store.settings.public_url,'id':result['id'],'machine_key':result['machine_key']}
                    result['script']=(STATIC/'machine_agent.py').read_text().replace('CONFIG = None  # Filled only in the private downloaded copy.','CONFIG = '+repr(config))
                    return self.reply(201,result)
                if self.command=='POST' and machine_page.group(2):
                    if set(data)!={'enabled'}:raise APIError(400,'only enabled is accepted')
                    return self.reply(200,manager.enable(machine_page.group(1),machine_page.group(2),data['enabled']))
            machine_report=re.fullmatch(r'/v1/machines/([0-9a-f]{32})/telemetry',route)
            if machine_report and self.command=='POST':
                auth=self.headers.get('Authorization','')
                return self.reply(200,self.server.store.machines.ingest(auth[7:] if auth.startswith('Bearer ') else '',machine_report.group(1),data))
'''
    text=once(text,"            dashboard=re.fullmatch(r'/v1/dashboard/",routes+"            dashboard=re.fullmatch(r'/v1/dashboard/")
    text=once(text,'self.server.store.dashboard(dashboard.group(1),','self.server.store.machines.dashboard(dashboard.group(1),')
    return text.encode()

def patch_html(source):
    text=source.decode().replace('\r\n','\n')
    start=text.index('<section class="overview">');end=text.index('</section>',start)+len('</section>')
    overview='''<section class="overview machine-overview" aria-label="机器资源监控"><div class="machine-toolbar"><div class="machine-section-title">机器状态 <span id="machine-count">可选接入</span></div><button id="add-machine" class="machine-add" type="button">＋ 接入机器</button></div><div id="summary" class="machine-grid"></div><div id="machine-empty" class="machine-empty">接入后查看 CPU、GPU、内存、磁盘和温度；实验提醒不依赖此功能。</div></section>'''
    text=text[:start]+overview+text[end:]
    dialog='''<dialog id="machine-setup" class="machine-setup"><div class="machine-setup-head"><h2>接入一台机器</h2><button id="close-machine-setup" type="button" aria-label="关闭">×</button></div><p>在你有权限的机器运行采集脚本。只上报资源指标，不开放端口，也不上传文件或进程信息。</p><label for="machine-name">机器名称</label><input id="machine-name" maxlength="60" placeholder="例如：训练工作站 / 云主机 A"><button id="create-machine" type="button" class="machine-primary">生成并下载采集脚本</button><p id="machine-setup-notice" role="status"></p><p class="machine-setup-hint">下载后在目标机器运行 <code>python endnote-machine.py</code>。Python 3.10+，每 15 秒上报；关闭脚本就停止采集。GPU 指标需要可用的 NVIDIA 驱动，缺失的指标显示“暂无数据”。脚本含这台机器的专用凭据，请勿公开分享。</p></dialog>'''
    return once(text,'</main><dialog id="detail">','</main>'+dialog+'<dialog id="detail">').encode()
