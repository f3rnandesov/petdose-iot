from nicegui import ui, app
import paho.mqtt.client as mqtt
from datetime import datetime

# --- ESTADO DO SISTEMA ---
dados = {'nivel': '--', 'status': 'Aguardando conexão...', 'acionamentos': 0}
logs = []

# --- CONFIGURAÇÃO MQTT ---
def on_connect(client, userdata, flags, rc, properties=None):
    dados['status'] = 'Online'
    client.subscribe("petdose/uema/status")
    client.subscribe("petdose/uema/nivel")

def on_message(client, userdata, msg):
    topico = msg.topic
    payload = msg.payload.decode()
    hora = datetime.now().strftime("%H:%M:%S")
    
    if topico == "petdose/uema/nivel":
        dados['nivel'] = payload
    elif topico == "petdose/uema/status":
        dados['status'] = payload
        logs.insert(0, {'hora': hora, 'msg': payload, 'tipo': 'sucesso' if 'SUCESSO' in payload else 'erro'})
        if 'SUCESSO' in payload:
            dados['acionamentos'] += 1
        if len(logs) > 10:
            logs.pop()

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect("broker.hivemq.com", 1883, 60)
mqtt_client.loop_start()

def enviar_comando():
    mqtt_client.publish("petdose/uema/comando", "alimentar")
    ui.notify('Comando enviado ao dispositivo', position='top', type='info')

# --- INTERFACE GRÁFICA (UI/UX) ---
@ui.page('/')
def painel_principal():
    # Paleta de Cores SaaS
    ui.colors(primary='#0f172a', secondary='#3b82f6', accent='#10b981', positive='#22c55e', negative='#ef4444')
    
    # Cabeçalho
    with ui.header(elevated=True).classes('bg-primary text-white items-center justify-between px-6 py-3'):
        with ui.row().classes('items-center gap-4'):
            ui.button(on_click=lambda: drawer.toggle(), icon='menu').props('flat color=white')
            ui.icon('pets', size='md')
            ui.label('PetDose').classes('text-2xl font-bold tracking-wider')
        
        with ui.row().classes('items-center gap-4'):
            ui.label('Admin (Abrigo São Luís)').classes('text-sm opacity-80')
            ui.avatar('person').classes('bg-secondary')

    # Menu Lateral (Sidebar)
    with ui.left_drawer(elevated=True).classes('bg-slate-50 border-r border-gray-200') as drawer:
        with ui.column().classes('w-full mt-4 gap-2 px-4'):
            ui.label('MENU PRINCIPAL').classes('text-xs font-bold text-gray-400 mb-2')
            ui.button('Painel de Controlo', icon='dashboard').classes('w-full justify-start').props('flat color=primary')
            ui.button('Meus Dispositivos', icon='router').classes('w-full justify-start').props('flat color=gray')
            ui.button('Assinatura e Pagamento', icon='credit_card').classes('w-full justify-start').props('flat color=gray')
            ui.button('Configurações', icon='settings').classes('w-full justify-start').props('flat color=gray')
            
            ui.space()
            ui.label('Plano Atual: Pro (Ativo)').classes('text-xs font-bold text-green-600 bg-green-100 p-2 rounded w-full text-center mt-auto')

    # Área de Conteúdo Principal
    with ui.column().classes('max-w-6xl mx-auto w-full p-6 gap-6'):
        
        ui.label('Visão Geral do Dispositivo').classes('text-3xl font-bold text-gray-800')
        
        # Cartões de Métricas (KPIs)
        with ui.row().classes('w-full gap-6'):
            # KPI Nível
            with ui.card().classes('col shadow-md rounded-xl p-6 border-t-4 border-secondary'):
                ui.label('Nível de Ração').classes('text-sm font-semibold text-gray-500 uppercase')
                nivel_label = ui.label(f"{dados['nivel']} cm").classes('text-4xl font-bold text-gray-800 mt-2')
                ui.icon('straighten', size='lg').classes('absolute top-6 right-6 text-gray-300')

            # KPI Status
            with ui.card().classes('col shadow-md rounded-xl p-6 border-t-4 border-primary'):
                ui.label('Estado do Mecanismo').classes('text-sm font-semibold text-gray-500 uppercase')
                status_label = ui.label(dados['status']).classes('text-2xl font-bold mt-2')
                ui.icon('health_and_safety', size='lg').classes('absolute top-6 right-6 text-gray-300')

            # KPI Acionamentos
            with ui.card().classes('col shadow-md rounded-xl p-6 border-t-4 border-accent'):
                ui.label('Refeições Hoje').classes('text-sm font-semibold text-gray-500 uppercase')
                refeicoes_label = ui.label(str(dados['acionamentos'])).classes('text-4xl font-bold text-gray-800 mt-2')
                ui.icon('restaurant', size='lg').classes('absolute top-6 right-6 text-gray-300')

        # Painel de Ação e Logs
        with ui.row().classes('w-full gap-6 mt-4'):
            # Coluna de Comando
            with ui.column().classes('col-4'):
                with ui.card().classes('w-full shadow-md rounded-xl p-6'):
                    ui.label('Ação Manual').classes('text-lg font-bold text-gray-800 mb-4')
                    ui.label('Acione o dispensador remotamente para uma alimentação extra.').classes('text-sm text-gray-500 mb-6')
                    ui.button('ALIMENTAR PET', on_click=enviar_comando, icon='touch_app').classes('w-full py-3 text-lg font-bold shadow-lg').props('color=secondary rounded')
            
            # Coluna de Auditoria
            with ui.column().classes('col-8'):
                with ui.card().classes('w-full shadow-md rounded-xl p-6'):
                    ui.label('Auditoria e Ocorrências').classes('text-lg font-bold text-gray-800 mb-4')
                    log_container = ui.column().classes('w-full gap-0')

        # Atualização em Tempo Real (Timer)
        def atualizar_interface():
            nivel_label.set_text(f"{dados['nivel']} cm")
            refeicoes_label.set_text(str(dados['acionamentos']))
            status_label.set_text(dados['status'])
            
            if "SUCESSO" in dados['status']:
                status_label.classes(replace='text-2xl font-bold mt-2 text-green-600')
            elif "FALHA" in dados['status'] or "ERRO" in dados['status']:
                status_label.classes(replace='text-2xl font-bold mt-2 text-red-600')
            else:
                status_label.classes(replace='text-2xl font-bold mt-2 text-gray-800')

            log_container.clear()
            with log_container:
                if not logs:
                    ui.label("Sem registos recentes.").classes('text-gray-400 p-4')
                for log in logs:
                    cor_texto = 'text-green-600' if log['tipo'] == 'sucesso' else 'text-red-600'
                    with ui.row().classes('w-full justify-between items-center py-3 border-b border-gray-100 hover:bg-gray-50 px-2 rounded transition-colors'):
                        with ui.row().classes('items-center gap-3'):
                            ui.icon('check_circle' if log['tipo'] == 'sucesso' else 'error', color='green' if log['tipo'] == 'sucesso' else 'red')
                            ui.label(log['msg']).classes(f'font-medium {cor_texto}')
                        ui.label(log['hora']).classes('text-xs text-gray-400 font-mono')

        ui.timer(1.0, atualizar_interface)

ui.run(title='PetDose Workspace', port=8080)