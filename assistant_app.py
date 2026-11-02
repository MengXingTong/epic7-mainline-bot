"""Unified lightweight desktop UI. Transport and task choices are independent."""
from __future__ import annotations
import argparse,ctypes,json,os,queue,subprocess,sys,threading,time,uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk
from assistant_config import CODE_ROOT,HOME,load_settings,atomic_json,read_json,validate_run,window_layout
BG,CARD,INK,MUTED,GREEN,LINE='#f3f6f4','#ffffff','#203c35','#6b8078','#087b65','#dce6e0'
CLIENTS={'自动识别':'auto','MuMu 模拟器':'mumu','PC 桌面端':'pc'}
TASKS={'普通深渊':'abyss','主线推进':'mainline'}
INPUTS={'后台窗口消息 · 实验性':'messages','前台兼容模式':'foreground'}

class Assistant:
    def __init__(self,root,ui_check=False):
        self.root=root;self.ui_check=ui_check;self.settings=load_settings();self.targets=[];self.filtered=[]
        self.process=None;self.run_dir=None;self.run_id=None;self.mode='idle';self.events=queue.Queue();self.photo=None;self.preview_stamp=None;self.started=None;self.last_heartbeat=time.monotonic();self.closing=False
        root.title('第七史诗 · 统一推进助手');root.configure(bg=BG)
        from ctypes import wintypes
        area=wintypes.RECT();user=ctypes.WinDLL('user32',use_last_error=True)
        if user.SystemParametersInfoW(48,0,ctypes.byref(area),0):
            self.workarea=(area.left,area.top,area.right,area.bottom)
        else:self.workarea=(0,0,root.winfo_screenwidth(),root.winfo_screenheight())
        layout=window_layout(self.workarea,(root.winfo_screenwidth(),root.winfo_screenheight()))
        root.geometry(f"{layout['width']}x{layout['height']}+{layout['x']}+{layout['y']}")
        root.minsize(layout['min_width'],layout['min_height']);root.maxsize(layout['max_width'],layout['max_height'])
        root.protocol('WM_DELETE_WINDOW',self.close)
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('TCombobox',padding=5,font=('Microsoft YaHei UI',10))
        style.configure('TCheckbutton',background=CARD,foreground=INK,font=('Microsoft YaHei UI',9))
        style.configure('TSpinbox',padding=4,font=('Microsoft YaHei UI',10))
        self.footer=tk.Frame(root,bg=BG);self.footer.pack(side='bottom',fill='x',padx=20,pady=(8,14))
        viewport=tk.Frame(root,bg=BG);viewport.pack(side='top',fill='both',expand=True)
        self.body_canvas=tk.Canvas(viewport,bg=BG,highlightthickness=0,borderwidth=0)
        scrollbar=ttk.Scrollbar(viewport,orient='vertical',command=self.body_canvas.yview)
        scrollbar.pack(side='right',fill='y');self.body_canvas.pack(side='left',fill='both',expand=True)
        self.body_canvas.configure(yscrollcommand=scrollbar.set)
        outer=tk.Frame(self.body_canvas,bg=BG);self.body_content=outer
        body_window=self.body_canvas.create_window((0,0),window=outer,anchor='nw')
        outer.bind('<Configure>',lambda e:self.body_canvas.configure(scrollregion=self.body_canvas.bbox('all')))
        self.body_canvas.bind('<Configure>',lambda e:self.body_canvas.itemconfigure(body_window,width=e.width))
        root.bind('<MouseWheel>',lambda e:self.body_canvas.yview_scroll(-int(e.delta/120),'units') if not isinstance(e.widget,(tk.Text,ttk.Combobox,ttk.Spinbox)) else None)
        content=tk.Frame(outer,bg=BG);content.pack(fill='both',expand=True,padx=20,pady=(16,12));outer=content
        tk.Label(outer,text='EPIC SEVEN  /  ONE ASSISTANT',bg=BG,fg=GREEN,font=('Segoe UI',9,'bold')).pack(anchor='w')
        tk.Label(outer,text='统一推进助手',bg=BG,fg=INK,font=('Microsoft YaHei UI',22,'bold')).pack(anchor='w',pady=(4,2))
        tk.Label(outer,text='双端适配 · 主线与普通深渊 · 保留原始进度',bg=BG,fg=MUTED,font=('Microsoft YaHei UI',10)).pack(anchor='w',pady=(0,13))
        connection=self.card(outer)
        connection.columnconfigure(1,weight=1)
        self.client=tk.StringVar(value=next(k for k,v in CLIENTS.items() if v==self.settings.get('client','auto')))
        self.task=tk.StringVar(value=next(k for k,v in TASKS.items() if v==self.settings.get('task','abyss')))
        self.input=tk.StringVar(value=next(k for k,v in INPUTS.items() if v==self.settings.get('pc_input','messages')))
        self.instance=tk.StringVar(value='正在检测客户端…')
        self.client_box=self.combo(connection,'客户端',self.client,list(CLIENTS),0)
        self.refresh_button=self.button(connection,'刷新',self.scan,'#e8f0eb',INK);self.refresh_button.grid(row=0,column=2,padx=(8,0))
        self.target_box=self.combo(connection,'绑定实例',self.instance,[],1,columnspan=2)
        self.task_box=self.combo(connection,'推进任务',self.task,list(TASKS),2,columnspan=2)
        self.input_box=self.combo(connection,'桌面输入',self.input,list(INPUTS),3,columnspan=2)
        self.client_box.bind('<<ComboboxSelected>>',lambda e:self.filter_targets())
        self.target_box.bind('<<ComboboxSelected>>',lambda e:self.update_note())
        self.task_box.bind('<<ComboboxSelected>>',lambda e:self.update_note())
        self.input_box.bind('<<ComboboxSelected>>',lambda e:self.update_note())
        status_card=self.card(outer)
        self.status=tk.StringVar(value='就绪 · 请选择客户端与推进任务')
        tk.Label(status_card,textvariable=self.status,bg=CARD,fg=GREEN,font=('Microsoft YaHei UI',10,'bold'),wraplength=550,justify='left').pack(anchor='w')
        stats=tk.Frame(status_card,bg=CARD);stats.pack(fill='x',pady=(9,0))
        self.scene=tk.StringVar(value='—');self.wins=tk.StringVar(value='0');self.elapsed=tk.StringVar(value='00:00')
        for title,var in [('当前界面',self.scene),('本次通关',self.wins),('运行时长',self.elapsed)]:
            cell=tk.Frame(stats,bg=CARD);cell.pack(side='left',fill='x',expand=True)
            tk.Label(cell,text=title,bg=CARD,fg=MUTED,font=('Microsoft YaHei UI',9)).pack(anchor='w')
            tk.Label(cell,textvariable=var,bg=CARD,fg=INK,font=('Microsoft YaHei UI',10),wraplength=210,justify='left').pack(anchor='w',pady=(3,0))
        preview_card=self.card(outer)
        tk.Label(preview_card,text='客户端画面',bg=CARD,fg=INK,font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w')
        self.preview=tk.Label(preview_card,bg='#eaf0ec',fg=MUTED,text='开始观察后显示游戏画面\n\n截图仅在本机处理，不上传',font=('Microsoft YaHei UI',10),height=6)
        self.preview.pack(fill='x',pady=(8,0))
        options=self.card(outer)
        row=tk.Frame(options,bg=CARD);row.pack(fill='x')
        tk.Label(row,text='本次最多推进',bg=CARD,fg=INK,font=('Microsoft YaHei UI',10)).pack(side='left')
        self.limit=tk.StringVar(value=str(self.settings.get('limit',3)))
        self.limit_box=ttk.Spinbox(row,from_=1,to=30,width=4,textvariable=self.limit);self.limit_box.pack(side='left',padx=8)
        tk.Label(row,text='关 / 层',bg=CARD,fg=MUTED,font=('Microsoft YaHei UI',9)).pack(side='left')
        self.observe=tk.BooleanVar(value=bool(self.settings.get('observe',True)));self.confirm=tk.BooleanVar(value=False)
        self.observe_box=ttk.Checkbutton(options,text='仅观察，不发送任何点击',variable=self.observe,command=self.update_buttons);self.observe_box.pack(anchor='w',pady=(9,3))
        self.confirm_box=ttk.Checkbutton(options,text='已确认当前队伍及原生自动战斗，允许运行所选模式',variable=self.confirm);self.confirm_box.pack(anchor='w')
        tk.Label(options,text='仅普通深渊 · 不购买 / 不复活 / 不重试战败关卡',bg='#e8f4ec',fg=GREEN,font=('Microsoft YaHei UI',9),padx=8,pady=7).pack(fill='x',pady=(9,0))
        actions=tk.Frame(self.footer,bg=BG);actions.pack(fill='x')
        self.start_button=self.button(actions,'开始观察',self.start,GREEN,'white');self.start_button.pack(side='left',fill='x',expand=True,padx=(0,8))
        self.pause_button=self.button(actions,'暂停',self.pause,'#e2ebe5',INK);self.pause_button.pack(side='left',padx=(0,8))
        self.stop_button=self.button(actions,'停止',self.stop,'#e2ebe5',INK);self.stop_button.pack(side='left')
        self.note=tk.StringVar()
        tk.Label(outer,textvariable=self.note,bg=BG,fg='#86602c',font=('Microsoft YaHei UI',9),wraplength=590,justify='left').pack(anchor='w',pady=(0,7))
        self.logs=tk.Text(outer,height=3,bg='#e9efeb',fg=MUTED,font=('Microsoft YaHei UI',9),relief='flat',padx=9,pady=7,wrap='word',state='disabled')
        self.logs.pack(fill='both',expand=True)
        self.update_note();self.update_buttons()
        if not ui_check:root.after(300,self.scan);root.after(200,self.pump)

    def card(self,parent):
        border=tk.Frame(parent,bg=CARD,highlightbackground=LINE,highlightthickness=1);border.pack(fill='x',pady=(0,10))
        inner=tk.Frame(border,bg=CARD);inner.pack(fill='both',expand=True,padx=13,pady=11);return inner
    def combo(self,parent,label,var,values,row,columnspan=1):
        tk.Label(parent,text=label,bg=CARD,fg=MUTED,font=('Microsoft YaHei UI',9)).grid(row=row,column=0,sticky='w',padx=(0,12),pady=4)
        box=ttk.Combobox(parent,textvariable=var,values=values,state='readonly',font=('Microsoft YaHei UI',10))
        box.grid(row=row,column=1,columnspan=columnspan,sticky='ew',pady=4);return box
    def button(self,parent,text,command,bg,fg):
        return tk.Button(parent,text=text,command=command,bg=bg,fg=fg,activebackground=bg,relief='flat',bd=0,padx=17,pady=9,font=('Microsoft YaHei UI',10,'bold'),cursor='hand2')
    def log(self,text):
        self.logs.configure(state='normal');self.logs.insert('end',time.strftime('%H:%M:%S')+'  '+text+'\n');self.logs.see('end')
        if int(self.logs.index('end-1c').split('.')[0])>160:self.logs.delete('1.0','30.0')
        self.logs.configure(state='disabled')
    def selected_target(self):
        rows=[t for t in self.filtered if t['label']==self.instance.get()]
        if len(rows)!=1:raise ValueError('请选择具体客户端/实例；多个目标不会自动切换。')
        return rows[0]
    def current_settings(self):
        value=dict(self.settings)
        value.update(client=CLIENTS[self.client.get()],task=TASKS[self.task.get()],pc_input=INPUTS[self.input.get()],limit=int(self.limit.get()),observe=self.observe.get())
        return value
    def filter_targets(self):
        client=CLIENTS[self.client.get()]
        self.filtered=[t for t in self.targets if client=='auto' or t['client']==client]
        self.target_box.configure(values=[t['label'] for t in self.filtered])
        if len(self.filtered)==1:self.instance.set(self.filtered[0]['label'])
        elif not self.filtered:self.instance.set('未检测到所选客户端')
        else:self.instance.set('检测到多个目标，请手动选择')
        self.update_note()
    def update_note(self):
        try:target=self.selected_target();client=target['client']
        except ValueError:client=CLIENTS.get(self.client.get())
        if client=='mumu':
            text='MuMu 使用 ADB，不占电脑鼠标和焦点；模拟器内需保持游戏打开。'
            if TASKS[self.task.get()]=='abyss':text+=' MuMu深渊尚未实机验收，无法确认界面时停止。'
        elif INPUTS[self.input.get()]=='messages':text='PC后台消息：已实测无焦点导航与截图；整场后台推进、拖动/CG仍待验收。不支持最小化。'
        else:text='PC前台兼容：需保持游戏前台、无遮挡；不会自动抢焦点。'
        if TASKS[self.task.get()]=='mainline':
            try:
                state=read_json(Path(self.settings.get('data_dir',''))/'state.json',{})
                text+=' 原主线记录 '+str(len(state.get('completed',{})))+' 关；'
                if state.get('terminal') or state.get('active'):text+='已有停止/未结算记录，不会清空或自动重试。'
            except Exception:text+='原主线记录需要检查，禁止空记录替代。'
        self.note.set(text)
    def update_buttons(self):self.start_button.configure(text='继续运行' if self.mode=='paused' else ('开始观察' if self.observe.get() else '开始推进'))
    def lock_choices(self,locked):
        for widget in (self.client_box,self.target_box,self.task_box,self.input_box):widget.configure(state='disabled' if locked else 'readonly')
        self.limit_box.configure(state='disabled' if locked else 'normal');self.refresh_button.configure(state='disabled' if locked else 'normal')
        self.observe_box.configure(state='disabled' if locked else 'normal');self.confirm_box.configure(state='disabled' if locked else 'normal')
    def scan(self):
        if self.process and self.process.poll() is None:return
        self.status.set('正在检测本机客户端…');HOME.mkdir(parents=True,exist_ok=True)
        settings_path=HOME/'discovery-settings.json';atomic_json(settings_path,self.settings)
        def work():
            try:
                py=self.settings.get('worker_python','')
                if not Path(py).is_file():raise ValueError('未找到已有工作运行库；没有自动下载或新建进度。')
                r=subprocess.run([py,'-B','-X','utf8',str(CODE_ROOT/'assistant_worker.py'),'--discover',str(settings_path)],capture_output=True,text=True,encoding='utf-8',timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode:raise ValueError(r.stderr.strip()[-500:])
                self.events.put(('targets',json.loads(r.stdout)['targets']))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=work,daemon=True).start()
    def start(self):
        if self.process and self.process.poll() is None:
            if self.mode=='paused':self.command('run');self.mode='run';self.last_heartbeat=time.monotonic();self.update_buttons()
            else:self.status.set('当前任务仍在运行；先暂停或停止后再切换。')
            return
        try:
            settings=self.current_settings();target=self.selected_target();validate_run(settings,target)
            if not settings['observe'] and not self.confirm.get():raise ValueError('请先确认队伍、原生自动战斗，并允许运行所选模式。')
            py=settings.get('worker_python','')
            if not Path(py).is_file():raise ValueError('工作运行库不存在，停止启动。')
            self.settings=settings;atomic_json(HOME/'settings.json',settings)
            self.run_id=uuid.uuid4().hex;self.run_dir=HOME/'runs'/self.run_id;self.run_dir.mkdir(parents=True)
            request={'run_id':self.run_id,'run_dir':str(self.run_dir),'home':str(HOME),'settings':settings,'target':target}
            atomic_json(self.run_dir/'request.json',request);self.command('run')
            self.process=subprocess.Popen([py,'-B','-X','utf8',str(CODE_ROOT/'assistant_worker.py'),'--request',str(self.run_dir/'request.json')],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',bufsize=1,cwd=str(CODE_ROOT),creationflags=subprocess.CREATE_NO_WINDOW)
            atomic_json(HOME/'active-run.json',{'run_id':self.run_id,'run_dir':str(self.run_dir),'worker_pid':self.process.pid})
            self.mode='starting';self.started=time.monotonic();self.last_heartbeat=time.monotonic();self.lock_choices(True);self.status.set('正在连接所选客户端…');self.preview_stamp=None
            child=self.process
            def reader():
                with (self.run_dir/'worker.log').open('a',encoding='utf-8') as log:
                    for line in child.stdout:
                        log.write(line);log.flush()
                        try:self.events.put(('worker',json.loads(line)))
                        except ValueError:self.events.put(('log',line.strip()))
                self.events.put(('exit',child.pid))
            threading.Thread(target=reader,daemon=True).start()
        except Exception as exc:self.status.set(str(exc));self.log(str(exc))
    def command(self,action):
        if self.run_dir:atomic_json(self.run_dir/'control.json',{'run_id':self.run_id,'action':action})
    def pause(self):
        if self.process and self.process.poll() is None:self.command('pause');self.status.set('正在安全暂停；不清除本次上下文。')
    def stop(self):
        if self.process and self.process.poll() is None:self.command('stop');self.status.set('正在停止输入，保留全部进度…')
    def pump(self):
        try:
            for _ in range(50):
                kind,data=self.events.get_nowait()
                if kind=='targets':self.targets=data;self.filter_targets();self.status.set('已发现 '+str(len(data))+' 个可绑定客户端；默认只观察。')
                elif kind in ('error','log'):self.log(data);self.status.set(data) if kind=='error' else None
                elif kind=='worker':
                    if data.get('kind')=='status':
                        if data.get('run_id')!=self.run_id:continue
                        self.mode=data['mode'];self.status.set(data['status']);self.scene.set(data.get('scene','—'));self.wins.set(str(data.get('wins',0)));self.last_heartbeat=time.monotonic();self.update_buttons()
                    elif data.get('kind')=='log':self.log(data['text'])
                elif kind=='exit' and self.process and data==self.process.pid:
                    self.lock_choices(False)
                    if self.mode not in ('done','blocked','stopped'):self.mode='blocked';self.status.set('工作进程已退出，未自动重启。')
                    self.update_buttons()
        except queue.Empty:pass
        if self.started and self.process and self.process.poll() is None:
            seconds=int(time.monotonic()-self.started);self.elapsed.set(f'{seconds//60:02d}:{seconds%60:02d}')
            if self.mode!='paused' and time.monotonic()-self.last_heartbeat>65:
                self.command('stop');self.process.terminate();self.status.set('工作进程超过65秒无响应，已停止自己的进程；不重启游戏。');self.mode='blocked'
        if self.run_dir:
            path=self.run_dir/'preview.png'
            try:
                stamp=path.stat().st_mtime_ns
                if stamp!=self.preview_stamp:
                    with Image.open(path) as source:image=source.copy()
                    image.thumbnail((560,165),Image.Resampling.LANCZOS);self.photo=ImageTk.PhotoImage(image);self.preview.configure(image=self.photo,text='',height=165);self.preview_stamp=stamp
            except OSError:pass
        if not self.closing:self.root.after(200,self.pump)
    def close(self):
        self.closing=True;self.command('stop');deadline=time.monotonic()+10
        def finish():
            if self.process and self.process.poll() is None and time.monotonic()<deadline:self.root.after(100,finish);return
            if self.process and self.process.poll() is None:self.process.terminate()
            self.root.destroy()
        finish()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--ui-check',action='store_true');ap.add_argument('--ui-exercise',action='store_true');ap.add_argument('--client',choices=('auto','mumu','pc'));ap.add_argument('--task',choices=('mainline','abyss'));args=ap.parse_args()
    locks=[]
    if not args.ui_check:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p];kernel.CreateMutexW.restype=ctypes.c_void_p
        for name in ('Local\\Epic7UnifiedAssistant','Local\\EpicSevenAbyssPilot.Panel'):
            handle=kernel.CreateMutexW(None,False,name)
            if not handle or ctypes.get_last_error()==183:return
            locks.append(handle)
    root=tk.Tk();app=Assistant(root,args.ui_check)
    if args.client:app.client.set(next(k for k,v in CLIENTS.items() if v==args.client))
    if args.task:app.task.set(next(k for k,v in TASKS.items() if v==args.task))
    app.update_note()
    if args.ui_exercise:
        app.observe.set(True);app.task.set('普通深渊');app.client.set('PC 桌面端');app.update_buttons()
        phase=[0];deadline=time.monotonic()+50
        def exercise():
            if phase[0]==0 and app.filtered:
                app.start();phase[0]=1
            elif phase[0]==1 and app.mode=='observe':
                app.pause();phase[0]=2
            elif phase[0]==2 and app.mode=='paused':
                app.start();phase[0]=3
            elif phase[0]==3 and app.mode=='observe':
                app.stop();phase[0]=4
            elif phase[0]==4 and app.mode=='stopped' and app.process.poll() is not None:
                atomic_json(HOME/'ui-exercise.json',{'passed':True,'run_id':app.run_id,'sequence':['observe','pause','resume_observe','stop'],'no_input_mode':True});return
            if time.monotonic()>deadline:
                app.stop();atomic_json(HOME/'ui-exercise.json',{'passed':False,'phase':phase[0],'status':app.status.get()});return
            root.after(300,exercise)
        root.after(500,exercise)
    if args.ui_check:
        root.update_idletasks();root.update()
        image=Image.new('RGB',(294,165),'#e8f4ec');app.photo=ImageTk.PhotoImage(image);app.preview.configure(image=app.photo,text='',height=165)
        root.update_idletasks();root.update()
        result={'width':root.winfo_width(),'height':root.winfo_height(),'workarea':app.workarea,'client_bounds':[root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height()],'scroll_region':app.body_canvas.cget('scrollregion'),'footer_bottom':app.stop_button.winfo_rooty()+app.stop_button.winfo_height(),'controls_visible':app.stop_button.winfo_ismapped(),'client_modes':list(CLIENTS.values()),'tasks':list(TASKS.values())}
        atomic_json(HOME/'ui-check.json',result);root.after(500,root.destroy)
    root.mainloop()

if __name__=='__main__':main()
