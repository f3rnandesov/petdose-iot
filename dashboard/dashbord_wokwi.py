from nicegui import ui, app
import paho.mqtt.client as mqtt
from datetime import datetime
import json

# --- CONTAS E PLANOS COMERCIAIS ---
USUARIOS = {
    'residencial': {
        'senha': '1234',
        'nome': 'Carlos Silva (Casa)',
        'plano': 'residencial',
        'max_pets': 2,
    },
    'tutor': {
        'senha': 'tutor',
        'nome': 'Canil & Abrigo São Luís',
        'plano': 'tutor',
        'max_pets': None,  # Ilimitado
    },
}

# --- ESTADO GLOBAL E TELEMETRIA ---
estado = {
    'mqtt_conectado': False,
    'modo_transporte': 'TCP:1883',
    'comedouro_online': False,
    'pct': 0,
    'estoque_g': 0,
    'status': 'Aguardando resposta do comedouro...',
    'total_gramas_hoje': 0,
    'refeicoes_hoje': 0,
    'pet_selecionado': 'Thor',
    'broker': 'broker.emqx.io',
    'tentativas_tcp': 0,
}

pets = {
    'Thor': {'especie': 'Cão', 'peso_kg': 25.0, 'refeicoes_dia': 2, 'gramas': 250, 'local': 'Baia 01 • Adoção'},
    'Mia':  {'especie': 'Gato', 'peso_kg': 4.5, 'refeicoes_dia': 2, 'gramas': 60, 'local': 'Gataria • Matriz'},
}

horarios = [
    {'hora': '08:00', 'pet': 'Thor'},
    {'hora': '08:05', 'pet': 'Mia'},
]

logs = []
disparados_minuto = set()

# --- CLIENTE DE COMUNICAÇÃO COM FALLBACK AUTOMÁTICO ---
def configurar_mqtt(usar_websockets: bool = False):
    global mqtt_client
    try:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
    except Exception:
        pass

    transporte = 'websockets' if usar_websockets else 'tcp'
    porta = 8083 if usar_websockets else 1883
    estado['modo_transporte'] = f'WS:{porta}' if usar_websockets else f'TCP:{porta}'

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport=transporte)
    if usar_websockets:
        cliente.ws_set_options(path="/mqtt")

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            estado['mqtt_conectado'] = True
            client.subscribe("petdose/uema/status")
            client.subscribe("petdose/uema/nivel")
            sincronizar_pet_ativo()
            client.publish("petdose/uema/ping", "PING")

    def on_disconnect(client, userdata, flags, rc, properties=None):
        estado['mqtt_conectado'] = False

    def on_message(client, userdata, msg):
        topico = msg.topic
        payload = msg.payload.decode()
        hora_atual = datetime.now().strftime("%H:%M:%S")
        estado['comedouro_online'] = True

        if topico == "petdose/uema/nivel":
            try:
                dados_nivel = json.loads(payload)
                estado['pct'] = int(dados_nivel.get('pct', 0))
                estado['estoque_g'] = int(dados_nivel.get('estoque_g', 0))
            except Exception:
                pass

        elif topico == "petdose/uema/status":
            if payload == "PONG":
                estado['status'] = "Pronto para servir"
                return

            estado['status'] = payload
            if 'SUCESSO' in payload:
                tipo = 'sucesso'
                estado['refeicoes_hoje'] += 1
                try:
                    gramas_servidas = int(payload.split(':')[1].strip().split('g')[0])
                    estado['total_gramas_hoje'] += gramas_servidas
                except Exception:
                    pass
            elif 'AVISO' in payload:
                tipo = 'aviso'
            else:
                tipo = 'erro'

            logs.insert(0, {'hora': hora_atual, 'msg': payload, 'tipo': tipo})
            if len(logs) > 30:
                logs.pop()

    cliente.on_connect = on_connect
    cliente.on_disconnect = on_disconnect
    cliente.on_message = on_message
    cliente.connect_async(estado['broker'], porta, 60)
    cliente.loop_start()
    return cliente

mqtt_client = configurar_mqtt(usar_websockets=False)

def sincronizar_pet_ativo():
    nome = estado['pet_selecionado']
    if nome in pets:
        payload = json.dumps({'pet': nome, 'gramas': pets[nome]['gramas']})
        mqtt_client.publish("petdose/uema/config", payload)

def verificar_conexao_comedouro():
    estado['comedouro_online'] = False
    mqtt_client.publish("petdose/uema/ping", "PING")
    ui.notify('Verificando conexão com o comedouro...', position='top-right', type='info')

def enviar_comando_alimentar(nome_pet: str, origem: str = "Manual"):
    if nome_pet not in pets:
        return
    gramas = pets[nome_pet]['gramas']
    payload = json.dumps({'pet': nome_pet, 'gramas': gramas})
    mqtt_client.publish("petdose/uema/comando", payload)
    ui.notify(f'Ordem enviada: {gramas}g para {nome_pet} ({origem})', position='top-right', type='info')

def calcular_porcao_ideal(especie: str, peso_kg: float, refeicoes_dia: int) -> int:
    fator = 20.0 if especie == 'Cão' else 25.0
    total_diario = peso_kg * fator
    porcao = round(total_diario / max(1, refeicoes_dia))
    return max(20, min(600, porcao))

# ==============================================================================
# TELA DE LOGIN (PLANO RESIDENCIAL VS. PLANO TUTOR)
# ==============================================================================
@ui.page('/login')
def pagina_login():
    if app.storage.user.get('autenticado'):
        ui.navigate.to('/')
        return

    with ui.column().classes('w-full min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-blue-950 to-slate-900 p-4'):
        with ui.card().classes('w-full max-w-lg p-8 rounded-2xl shadow-2xl bg-white/95 backdrop-blur'):
            with ui.column().classes('w-full items-center text-center mb-6'):
                with ui.avatar(color='blue-600', text_color='white').classes('w-16 h-16 shadow-lg mb-3'):
                    ui.icon('pets', size='lg')
                ui.label('PetDose').classes('text-3xl font-extrabold text-slate-800 tracking-tight')
                ui.label('Nutrição Inteligente e Automatizada para Pets').classes('text-xs text-slate-500 mt-1')

            user_input = ui.input(label='Usuário', placeholder='residencial ou tutor').classes('w-full mb-3').props('outlined prepend-icon=person')
            pass_input = ui.input(label='Senha', placeholder='Digite sua senha', password=True, password_toggle_button=True).classes('w-full mb-4').props('outlined prepend-icon=lock')

            def tentar_login():
                u = (user_input.value or '').strip().lower()
                s = (pass_input.value or '').strip()
                if u in USUARIOS and USUARIOS[u]['senha'] == s:
                    app.storage.user['autenticado'] = True
                    app.storage.user['usuario'] = u
                    app.storage.user['nome'] = USUARIOS[u]['nome']
                    app.storage.user['plano'] = USUARIOS[u]['plano']
                    app.storage.user['max_pets'] = USUARIOS[u]['max_pets']
                    ui.navigate.to('/')
                else:
                    ui.notify('Usuário ou senha inválidos.', type='negative', position='top')

            pass_input.on('keydown.enter', tentar_login)

            ui.button('ACESSAR PLATAFORMA', on_click=tentar_login, icon='login').classes('w-full py-3 font-bold text-white shadow-md').props('color=blue-700 rounded')

            ui.separator().classes('my-5')
            ui.label('Selecione o Perfil de Assinatura para Demonstração:').classes('text-xs font-semibold text-slate-500 text-center w-full mb-3')

            with ui.element('div').classes('grid grid-cols-1 sm:grid-cols-2 gap-3 w-full'):
                def entrar_rapido(u, s):
                    user_input.value = u
                    pass_input.value = s
                    tentar_login()

                with ui.card().classes('p-3 border border-blue-200 bg-blue-50/50 rounded-xl shadow-none cursor-pointer hover:bg-blue-100/70').on('click', lambda: entrar_rapido('residencial', '1234')):
                    with ui.row().classes('items-center gap-2 mb-1'):
                        ui.icon('home', color='blue-700', size='sm')
                        ui.label('Plano Residencial').classes('text-sm font-bold text-blue-950')
                    ui.label('Ideal para casas e apartamentos com 1 ou 2 pets domésticos.').classes('text-[11px] text-slate-600 leading-tight')

                with ui.card().classes('p-3 border border-purple-200 bg-purple-50/50 rounded-xl shadow-none cursor-pointer hover:bg-purple-100/70').on('click', lambda: entrar_rapido('tutor', 'tutor')):
                    with ui.row().classes('items-center gap-2 mb-1'):
                        ui.icon('storefront', color='purple-700', size='sm')
                        ui.label('Plano Tutor (Canil)').classes('text-sm font-bold text-purple-950')
                    ui.label('Canis de adoção e criadores. Pets ilimitados e gestão em escala.').classes('text-[11px] text-slate-600 leading-tight')

# ==============================================================================
# PAINEL PRINCIPAL MULTI-ABAS
# ==============================================================================
@ui.page('/')
def painel_principal():
    if not app.storage.user.get('autenticado'):
        ui.navigate.to('/login')
        return

    plano = app.storage.user.get('plano', 'residencial')
    nome_usuario = app.storage.user.get('nome', 'Usuário')
    max_pets = app.storage.user.get('max_pets', 2)
    is_plano_tutor = (plano == 'tutor')

    ui.colors(primary='#0f172a', secondary='#2563eb', accent='#10b981', positive='#16a34a', negative='#dc2626')
    ui.query('body').classes('bg-slate-100')

    def fazer_logout():
        app.storage.user.clear()
        ui.navigate.to('/login')

    # --- CABEÇALHO SUPERIOR (LIMPO, SEM JARGÃO TÉCNICO) ---
    with ui.header(elevated=True).classes('bg-slate-900 text-white items-center justify-between px-6 py-3'):
        with ui.row().classes('items-center gap-3'):
            ui.button(on_click=lambda: drawer.toggle(), icon='menu').props('flat round color=white')
            ui.icon('pets', size='md', color='blue-400')
            ui.label('PetDose').classes('text-xl font-extrabold tracking-wider')
            if is_plano_tutor:
                ui.badge('PLANO TUTOR • CANIL & CRIADOR', color='purple-600').classes('text-xs font-bold px-2.5 py-1')
            else:
                ui.badge('PLANO RESIDENCIAL (ATÉ 2 PETS)', color='blue-600').classes('text-xs font-bold px-2.5 py-1')

        with ui.row().classes('items-center gap-3'):
            conn_badge = ui.badge('Conectando...', color='amber').classes('text-xs px-3 py-1')
            comedouro_badge = ui.badge('Comedouro: Aguardando', color='slate-600').classes('text-xs px-3 py-1')
            with ui.row().classes('items-center gap-2 bg-slate-800 px-3 py-1 rounded-full'):
                ui.icon('storefront' if is_plano_tutor else 'home', size='sm', color='blue-300')
                ui.label(nome_usuario).classes('text-xs font-medium')
            ui.button('Trocar Plano / Sair', on_click=fazer_logout, icon='logout').props('flat dense color=red-300').classes('text-xs')

    # --- CONTROLE DE ABAS ---
    botoes_nav = {}
    tabs = ui.tabs().classes('hidden')
    with tabs:
        ui.tab('operacao')
        ui.tab('pets')
        ui.tab('rotinas')
        ui.tab('auditoria')
        if is_plano_tutor:
            ui.tab('gestao_tutor')

    def selecionar_aba(chave: str):
        tabs.set_value(chave)
        for k, btn in botoes_nav.items():
            if k == chave:
                btn.classes(replace='w-full justify-start px-4 py-3 rounded-xl font-bold bg-blue-600 text-white shadow-sm')
            else:
                btn.classes(replace='w-full justify-start px-4 py-3 rounded-xl font-medium text-slate-600 hover:bg-slate-200')

    # --- MENU LATERAL ---
    with ui.left_drawer(elevated=True).classes('bg-white border-r border-slate-200 p-4 flex flex-col justify-between') as drawer:
        with ui.column().classes('w-full gap-2'):
            ui.label('NAVEGAÇÃO').classes('text-xs font-bold text-slate-400 px-3 mb-1 tracking-wider')

            itens_menu = [
                ('operacao', 'Visão Geral & Disparo', 'dashboard'),
                ('pets', 'Pets & Dietas' if is_plano_tutor else 'Meus Pets (Máx. 2)', 'pets'),
                ('rotinas', 'Rotinas Programadas', 'schedule'),
                ('auditoria', 'Auditoria & Logs', 'history'),
            ]
            if is_plano_tutor:
                itens_menu.append(('gestao_tutor', 'Gestão Canil & Assinatura', 'storefront'))

            for chave, titulo, icone in itens_menu:
                btn = ui.button(titulo, icon=icone, on_click=lambda c=chave: selecionar_aba(c)).props('flat no-caps')
                botoes_nav[chave] = btn

            selecionar_aba('operacao')

        with ui.card().classes('w-full bg-slate-50 border border-slate-200 p-3 rounded-xl shadow-none gap-1'):
            ui.label('Assinatura Ativa').classes('text-[10px] font-bold text-slate-400 uppercase')
            ui.label('Plano Tutor (Ilimitado)' if is_plano_tutor else 'Plano Residencial (2 pets)').classes('text-xs font-bold text-slate-800')
            ui.label('R$ 99,90/mês' if is_plano_tutor else 'R$ 39,90/mês').classes('text-xs text-blue-600 font-semibold')

    # --- CONTEÚDO PRINCIPAL ---
    with ui.column().classes('max-w-7xl mx-auto w-full p-6'):
        with ui.tab_panels(tabs, value='operacao').classes('w-full bg-transparent p-0'):

            # ==================================================================
            # ABA 1: VISÃO GERAL & DISPARO
            # ==================================================================
            with ui.tab_panel('operacao').classes('p-0 flex flex-col gap-6'):

                with ui.row().classes('w-full justify-between items-center'):
                    with ui.column().classes('gap-0'):
                        ui.label('Visão Geral Operacional').classes('text-2xl font-extrabold text-slate-800 tracking-tight')
                        ui.label('Acompanhamento em tempo real do reservatório, pesagem automática e refeições').classes('text-xs text-slate-500')
                    with ui.row().classes('items-center gap-2'):
                        ui.button('Verificar Conexão', on_click=verificar_conexao_comedouro, icon='wifi_tethering').props('outline dense no-caps color=blue-700').classes('px-3 py-1.5 bg-white text-xs font-semibold rounded-lg')
                        ui.button('Atualizar Comedouro', on_click=lambda: (sincronizar_pet_ativo(), ui.notify('Dieta enviada ao comedouro', type='info')), icon='sync').props('outline dense no-caps color=slate-700').classes('px-3 py-1.5 bg-white text-xs font-semibold rounded-lg')

                # LINHA 1: 3 CARDS DE KPI NIVELADOS
                with ui.element('div').classes('grid grid-cols-1 md:grid-cols-3 gap-6 w-full'):

                    with ui.card().classes('h-full bg-white shadow-sm rounded-2xl p-6 border border-slate-200 flex flex-col justify-between'):
                        with ui.row().classes('w-full justify-between items-center'):
                            ui.label('Estoque do Reservatório').classes('text-xs font-bold text-slate-400 uppercase tracking-wider')
                            estoque_badge = ui.badge('Crítico', color='red').classes('px-2.5 py-0.5 font-semibold')
                        with ui.column().classes('w-full my-3 gap-2'):
                            estoque_pct_label = ui.label('0%').classes('text-4xl font-extrabold text-slate-800 leading-none')
                            estoque_bar = ui.linear_progress(value=0, show_value=False).classes('rounded-full h-2.5')
                        estoque_gramas_label = ui.label('~0g disponíveis de 2.000g').classes('text-xs text-slate-500 font-medium')

                    with ui.card().classes('h-full bg-white shadow-sm rounded-2xl p-6 border border-slate-200 flex flex-col justify-between'):
                        with ui.row().classes('w-full justify-between items-center'):
                            ui.label('Status do Comedouro').classes('text-xs font-bold text-slate-400 uppercase tracking-wider')
                            with ui.avatar(color='blue-50', text_color='blue-600', size='sm'):
                                ui.icon('scale', size='xs')
                        status_label = ui.label(estado['status']).classes('text-lg font-bold text-slate-800 my-3 leading-snug')
                        with ui.row().classes('items-center gap-1.5'):
                            ui.icon('verified', color='blue-500', size='xs')
                            ui.label('Pesagem automática de precisão ativa').classes('text-xs text-slate-500 font-medium')

                    with ui.card().classes('h-full bg-white shadow-sm rounded-2xl p-6 border border-slate-200 flex flex-col justify-between'):
                        with ui.row().classes('w-full justify-between items-center'):
                            ui.label('Nutrição Servida Hoje').classes('text-xs font-bold text-slate-400 uppercase tracking-wider')
                            with ui.avatar(color='emerald-50', text_color='emerald-600', size='sm'):
                                ui.icon('restaurant', size='xs')
                        total_g_label = ui.label('0 g').classes('text-4xl font-extrabold text-slate-800 my-3 leading-none')
                        refeicoes_sub = ui.label('0 refeições confirmadas').classes('text-xs text-slate-500 font-medium')

                # LINHA 2: GRID DE 12 COLUNAS
                with ui.element('div').classes('grid grid-cols-1 lg:grid-cols-12 gap-6 w-full items-stretch'):

                    # ESQUERDA (5/12): Alimentação Sob Demanda
                    with ui.card().classes('lg:col-span-5 h-full bg-white shadow-sm rounded-2xl p-6 border border-slate-200 flex flex-col justify-between'):
                        with ui.column().classes('w-full gap-4'):
                            with ui.row().classes('w-full justify-between items-start'):
                                with ui.column().classes('gap-0.5'):
                                    ui.label('Alimentação Sob Demanda').classes('text-lg font-bold text-slate-800')
                                    ui.label('Dosagem pesada individualmente para cada pet').classes('text-xs text-slate-500')
                                ui.button('Perfis', on_click=lambda: selecionar_aba('pets'), icon='tune').props('flat dense no-caps color=blue-600').classes('text-xs')

                            opcoes_iniciais = list(pets.keys())[:max_pets] if max_pets else list(pets.keys())
                            if estado['pet_selecionado'] not in opcoes_iniciais and opcoes_iniciais:
                                estado['pet_selecionado'] = opcoes_iniciais[0]

                            seletor_pet = ui.select(
                                options=opcoes_iniciais,
                                value=estado['pet_selecionado'],
                                label='Selecionar Pet',
                                on_change=lambda e: (
                                    estado.update({'pet_selecionado': e.value}),
                                    sincronizar_pet_ativo(),
                                    atualizar_info_pet_selecionado()
                                )
                            ).classes('w-full').props('outlined')

                            with ui.column().classes('w-full bg-blue-50/80 border border-blue-200 p-4 rounded-xl gap-1'):
                                ui.label('DIETA CONFIGURADA').classes('text-[10px] font-bold text-blue-600 uppercase tracking-wider')
                                info_porcao_label = ui.label('').classes('text-base font-extrabold text-blue-950')
                                info_detalhe_pet = ui.label('').classes('text-xs text-blue-700')

                            def atualizar_info_pet_selecionado():
                                p = pets.get(estado['pet_selecionado'])
                                if p:
                                    info_porcao_label.set_text(f"{p['gramas']}g por refeição • {estado['pet_selecionado']}")
                                    local_txt = f" • {p['local']}" if is_plano_tutor and p.get('local') else ""
                                    info_detalhe_pet.set_text(f"{p['especie']} • Peso: {p['peso_kg']} kg • {p['refeicoes_dia']}x/dia{local_txt}")

                            atualizar_info_pet_selecionado()

                        with ui.column().classes('w-full pt-5 mt-4 border-t border-slate-100 gap-2'):
                            ui.button(
                                'SERVIR PORÇÃO EXATA AGORA',
                                on_click=lambda: enviar_comando_alimentar(estado['pet_selecionado'], "Manual"),
                                icon='play_arrow'
                            ).classes('w-full py-3.5 font-bold text-white shadow-md tracking-wide').props('color=blue-600 rounded')
                            ui.label('Verifica automaticamente se há ração suficiente antes de servir.').classes('text-[11px] text-slate-400 text-center w-full')

                    # DIREITA (7/12): Rotinas Ativas + Últimas Ocorrências
                    with ui.column().classes('lg:col-span-7 h-full flex flex-col gap-6'):

                        with ui.card().classes('w-full bg-white shadow-sm rounded-2xl p-6 border border-slate-200'):
                            with ui.row().classes('w-full justify-between items-center mb-3'):
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon('schedule', color='blue-600', size='sm')
                                    ui.label('Rotinas Automáticas Ativas').classes('text-base font-bold text-slate-800')
                                ui.button('+ Gerenciar Horários', on_click=lambda: selecionar_aba('rotinas')).props('flat dense no-caps color=blue-600').classes('text-xs font-semibold')

                            resumo_rotinas_container = ui.row().classes('w-full gap-2.5 flex-wrap')

                        with ui.card().classes('w-full flex-grow bg-white shadow-sm rounded-2xl p-6 border border-slate-200 flex flex-col justify-between'):
                            with ui.column().classes('w-full'):
                                with ui.row().classes('w-full justify-between items-center mb-3'):
                                    with ui.row().classes('items-center gap-2'):
                                        ui.icon('history', color='slate-700', size='sm')
                                        ui.label('Últimas Ocorrências').classes('text-base font-bold text-slate-800')
                                    ui.button('Ver histórico completo', on_click=lambda: selecionar_aba('auditoria')).props('flat dense no-caps color=blue-600').classes('text-xs font-semibold')

                                mini_log_container = ui.column().classes('w-full gap-1')

                            with ui.row().classes('w-full justify-between items-center pt-3 border-t border-slate-100 mt-4'):
                                resumo_rodape_label = ui.label('').classes('text-xs text-slate-500 font-medium')
                                ui.button('Gerenciar Pets', on_click=lambda: selecionar_aba('pets'), icon='pets').props('outline dense no-caps color=slate-700').classes('text-xs px-3 rounded-lg')

            # ==================================================================
            # ABA 2: MEUS PETS & DIETAS
            # ==================================================================
            with ui.tab_panel('pets').classes('p-0 flex flex-col gap-6'):
                with ui.element('div').classes('grid grid-cols-1 lg:grid-cols-12 gap-6 w-full items-start'):

                    with ui.card().classes('lg:col-span-5 bg-white shadow-sm rounded-2xl p-6 border border-slate-200'):
                        with ui.row().classes('w-full justify-between items-center mb-1'):
                            ui.label('Cadastrar Animal').classes('text-lg font-bold text-slate-800')
                            if is_plano_tutor:
                                ui.badge('Pets Ilimitados', color='purple-100').classes('text-purple-900 font-bold text-xs')
                            else:
                                contador_limite_badge = ui.badge(f'{min(len(pets), 2)} / 2 Pets', color='blue-100').classes('text-blue-900 font-bold text-xs')

                        ui.label('O sistema calcula automaticamente a porção ideal pelo peso.').classes('text-xs text-slate-500 mb-4')

                        in_nome = ui.input(label='Nome / Identificação do Animal', placeholder='Ex: Mel' if not is_plano_tutor else 'Ex: Rex (Baia 02)').classes('w-full mb-3').props('outlined')

                        if is_plano_tutor:
                            in_local = ui.input(label='Baia / Finalidade (Canil ou Criação)', placeholder='Ex: Adoção - Baia 02 / Matriz').classes('w-full mb-3').props('outlined')
                        else:
                            in_local = None

                        with ui.element('div').classes('grid grid-cols-2 gap-3 w-full mb-3'):
                            in_especie = ui.select(['Cão', 'Gato'], value='Cão', label='Espécie').props('outlined')
                            in_peso = ui.number(label='Peso (kg)', value=10.0, min=0.5, max=80.0, step=0.5).props('outlined')

                        with ui.element('div').classes('grid grid-cols-2 gap-3 w-full mb-4'):
                            in_ref = ui.select({1: '1x ao dia', 2: '2x ao dia', 3: '3x ao dia'}, value=2, label='Frequência').props('outlined')
                            in_gramas = ui.number(label='Porção (g)', value=100, min=10, max=1000, step=5).props('outlined')

                        def recalcular_sugestao():
                            if in_peso.value and in_ref.value:
                                in_gramas.value = calcular_porcao_ideal(in_especie.value, float(in_peso.value), int(in_ref.value))

                        in_especie.on_value_change(lambda _: recalcular_sugestao())
                        in_peso.on_value_change(lambda _: recalcular_sugestao())
                        in_ref.on_value_change(lambda _: recalcular_sugestao())

                        def obter_pets_visiveis():
                            if max_pets:
                                chaves = list(pets.keys())[:max_pets]
                                return {k: pets[k] for k in chaves}
                            return pets

                        def atualizar_seletores_pets():
                            visiveis = obter_pets_visiveis()
                            opcoes = list(visiveis.keys())
                            seletor_pet.options = opcoes
                            if estado['pet_selecionado'] not in opcoes and opcoes:
                                estado['pet_selecionado'] = opcoes[0]
                            seletor_pet.value = estado['pet_selecionado']
                            seletor_pet.update()

                            sel_pet_agenda.options = opcoes
                            if sel_pet_agenda.value not in opcoes and opcoes:
                                sel_pet_agenda.value = opcoes[0]
                            sel_pet_agenda.update()

                            if not is_plano_tutor:
                                contador_limite_badge.set_text(f'{len(visiveis)} / 2 Pets')

                            atualizar_info_pet_selecionado()
                            sincronizar_pet_ativo()

                        def salvar_pet():
                            nome = (in_nome.value or '').strip()
                            if not nome:
                                ui.notify('Informe o nome do animal.', type='warning')
                                return

                            visiveis = obter_pets_visiveis()
                            if max_pets and nome not in visiveis and len(visiveis) >= max_pets:
                                ui.notify('Limite de 2 pets atingido no Plano Residencial! Migre para o Plano Tutor (Canil/Criador) para pets ilimitados.', type='negative', timeout=5000)
                                return

                            pets[nome] = {
                                'especie': in_especie.value,
                                'peso_kg': float(in_peso.value or 5.0),
                                'refeicoes_dia': int(in_ref.value or 2),
                                'gramas': int(in_gramas.value or 50),
                                'local': (in_local.value or '').strip() if in_local else 'Residencial'
                            }
                            estado['pet_selecionado'] = nome
                            atualizar_seletores_pets()
                            renderizar_cards_pets.refresh()
                            in_nome.value = ''
                            if in_local:
                                in_local.value = ''
                            ui.notify(f'Perfil de {nome} salvo!', type='positive')

                        ui.button('SALVAR PERFIL DO PET', on_click=salvar_pet, icon='save').classes('w-full py-3 font-bold text-white').props('color=blue-600 rounded')

                        if not is_plano_tutor:
                            with ui.row().classes('w-full items-center gap-2 mt-4 p-3 bg-amber-50 border border-amber-200 rounded-xl'):
                                ui.icon('info', color='amber-700', size='sm')
                                ui.label('Tem canil de adoção ou criação com mais de 2 animais? Faça login no Plano Tutor.').classes('text-[11px] text-amber-900 col')

                    with ui.column().classes('lg:col-span-7 gap-4'):
                        with ui.row().classes('w-full justify-between items-center'):
                            ui.label('Perfis Nutricionais Ativos').classes('text-lg font-bold text-slate-800')
                            if is_plano_tutor:
                                ui.label('Gestão completa de plantel e baias').classes('text-xs text-purple-700 font-semibold')

                        @ui.refreshable
                        def renderizar_cards_pets():
                            visiveis = obter_pets_visiveis()
                            with ui.column().classes('w-full gap-3'):
                                for nome, d in visiveis.items():
                                    ativo = (nome == estado['pet_selecionado'])
                                    borda = 'border-blue-500 ring-1 ring-blue-500' if ativo else 'border-slate-200'
                                    with ui.card().classes(f'w-full bg-white shadow-sm rounded-2xl p-4 border {borda}'):
                                        with ui.row().classes('w-full justify-between items-center'):
                                            with ui.row().classes('items-center gap-3'):
                                                with ui.avatar(color='purple-100' if is_plano_tutor else 'blue-100', text_color='purple-800' if is_plano_tutor else 'blue-800'):
                                                    ui.icon('pets')
                                                with ui.column().classes('gap-0'):
                                                    with ui.row().classes('items-center gap-2'):
                                                        ui.label(nome).classes('text-base font-bold text-slate-800')
                                                        if ativo:
                                                            ui.badge('Selecionado', color='blue')
                                                        if is_plano_tutor and d.get('local'):
                                                            ui.badge(d['local'], color='purple-100').classes('text-purple-900 text-[10px]')
                                                    ui.label(f"{d['especie']} • {d['peso_kg']} kg • {d['refeicoes_dia']}x/dia").classes('text-xs text-slate-500')

                                            with ui.row().classes('items-center gap-2'):
                                                ui.badge(f"{d['gramas']}g / porção", color='emerald-100').classes('text-emerald-900 font-bold px-3 py-1')
                                                ui.button(icon='restaurant', on_click=lambda n=nome: enviar_comando_alimentar(n, "Atalho")).props('flat round color=blue-600').tooltip('Servir agora')
                                                if len(visiveis) > 1:
                                                    def remover_pet(n=nome):
                                                        del pets[n]
                                                        atualizar_seletores_pets()
                                                        renderizar_cards_pets.refresh()
                                                    ui.button(icon='delete', on_click=remover_pet).props('flat round color=red-500').tooltip('Remover')

                        renderizar_cards_pets()

            # ==================================================================
            # ABA 3: ROTINAS PROGRAMADAS
            # ==================================================================
            with ui.tab_panel('rotinas').classes('p-0 flex flex-col gap-6'):
                with ui.card().classes('w-full bg-white shadow-sm rounded-2xl p-6 border border-slate-200'):
                    ui.label('Agendamento Automático por Animal').classes('text-lg font-bold text-slate-800 mb-1')
                    ui.label('O comedouro servirá automaticamente no horário configurado com a gramatura exata do pet.').classes('text-xs text-slate-500 mb-4')

                    opcoes_agenda = list(pets.keys())[:max_pets] if max_pets else list(pets.keys())

                    with ui.element('div').classes('grid grid-cols-1 md:grid-cols-12 gap-3 w-full items-center mb-6'):
                        in_hora = ui.input(label='Horário (HH:MM)', placeholder='Ex: 14:30').classes('md:col-span-4').props('outlined')
                        sel_pet_agenda = ui.select(options=opcoes_agenda, value=opcoes_agenda[0] if opcoes_agenda else None, label='Pet Vinculado').classes('md:col-span-5').props('outlined')

                        def adicionar_agendamento():
                            h = (in_hora.value or '').strip()
                            p = sel_pet_agenda.value
                            if len(h) == 5 and ':' in h and p:
                                horarios.append({'hora': h, 'pet': p})
                                horarios.sort(key=lambda x: x['hora'])
                                in_hora.value = ''
                                renderizar_agendamentos.refresh()
                                ui.notify(f'Rotina às {h} agendada para {p}.', type='positive')
                            else:
                                ui.notify('Informe um horário válido no formato HH:MM.', type='warning')

                        ui.button('ADICIONAR HORÁRIO', on_click=adicionar_agendamento, icon='add_alarm').classes('md:col-span-3 py-3.5 font-bold text-white').props('color=blue-600 rounded')

                    @ui.refreshable
                    def renderizar_agendamentos():
                        if not horarios:
                            ui.label('Nenhum horário programado.').classes('text-sm text-slate-400 py-4')
                            return
                        with ui.column().classes('w-full gap-2'):
                            for item in horarios:
                                g_pet = pets.get(item['pet'], {}).get('gramas', '--')
                                with ui.row().classes('w-full justify-between items-center bg-slate-50 border border-slate-200 px-4 py-3 rounded-xl'):
                                    with ui.row().classes('items-center gap-4'):
                                        ui.icon('alarm', color='blue-600', size='sm')
                                        ui.label(item['hora']).classes('text-lg font-mono font-bold text-slate-800')
                                        ui.label(f"Pet: {item['pet']}").classes('text-sm font-medium text-slate-700')
                                        ui.badge(f"{g_pet}g", color='blue-100').classes('text-blue-900 font-bold')
                                    ui.button(
                                        icon='delete_outline',
                                        on_click=lambda x=item: (horarios.remove(x), renderizar_agendamentos.refresh())
                                    ).props('flat round color=red-500')

                    renderizar_agendamentos()

            # ==================================================================
            # ABA 4: AUDITORIA & LOGS
            # ==================================================================
            with ui.tab_panel('auditoria').classes('p-0 flex flex-col gap-6'):
                with ui.card().classes('w-full bg-white shadow-sm rounded-2xl p-6 border border-slate-200'):
                    with ui.row().classes('w-full justify-between items-center mb-4'):
                        with ui.column().classes('gap-0'):
                            ui.label('Histórico de Auditoria e Ocorrências').classes('text-lg font-bold text-slate-800')
                            ui.label('Comprovação cronológica de entregas, bloqueios de duplicidade e alertas de estoque.').classes('text-xs text-slate-500')
                        if is_plano_tutor:
                            def limpar_logs():
                                logs.clear()
                                ui.notify('Histórico de auditoria limpo.', type='info')
                            ui.button('Limpar Histórico', on_click=limpar_logs, icon='delete_sweep').props('outline color=red-600').classes('text-xs')

                    log_container = ui.column().classes('w-full gap-0')

            # ==================================================================
            # ABA 5: GESTÃO CANIL & ASSINATURA (EXCLUSIVA DO PLANO TUTOR)
            # ==================================================================
            if is_plano_tutor:
                with ui.tab_panel('gestao_tutor').classes('p-0 flex flex-col gap-6'):
                    with ui.element('div').classes('grid grid-cols-1 md:grid-cols-3 gap-6 w-full'):
                        with ui.card().classes('h-full bg-white shadow-sm rounded-2xl p-6 border border-purple-200 flex flex-col justify-between'):
                            ui.label('Assinatura Comercial').classes('text-xs font-bold text-purple-600 uppercase')
                            ui.label('Plano Tutor (Canil/Criador)').classes('text-xl font-extrabold text-slate-800 my-2')
                            ui.label('R$ 99,90/mês • Animais ilimitados e comodato').classes('text-xs text-slate-500')

                        with ui.card().classes('h-full bg-white shadow-sm rounded-2xl p-6 border border-purple-200 flex flex-col justify-between'):
                            ui.label('Serviço em Nuvem').classes('text-xs font-bold text-purple-600 uppercase')
                            nuvem_status_label = ui.label('Conectado em Tempo Real').classes('text-xl font-extrabold text-slate-800 my-2')
                            ui.label('Sincronização automática com o comedouro').classes('text-xs text-slate-500')

                        with ui.card().classes('h-full bg-white shadow-sm rounded-2xl p-6 border border-purple-200 flex flex-col justify-between'):
                            ui.label('Plantel Cadastrado').classes('text-xs font-bold text-purple-600 uppercase')
                            plantel_label = ui.label(f"{len(pets)} animais").classes('text-2xl font-extrabold text-slate-800 my-2')
                            ui.label('Sem limite de baias ou perfis').classes('text-xs text-slate-500')

                    with ui.card().classes('w-full bg-white shadow-sm rounded-2xl p-6 border border-slate-200'):
                        ui.label('Ferramentas Operacionais do Canil / Criador').classes('text-lg font-bold text-slate-800 mb-3')
                        with ui.row().classes('w-full gap-4 flex-wrap'):
                            def alternar_rota_conexao():
                                global mqtt_client
                                mqtt_client = configurar_mqtt(usar_websockets=True)
                                ui.notify('Otimizando conexão com o comedouro...', type='info')

                            def zerar_contadores_dia():
                                estado['total_gramas_hoje'] = 0
                                estado['refeicoes_hoje'] = 0
                                disparados_minuto.clear()
                                ui.notify('Contadores diários zerados.', type='info')

                            ui.button('Verificar Conexão', on_click=verificar_conexao_comedouro, icon='wifi_tethering').props('color=purple-700')
                            ui.button('Otimizar Conexão', on_click=alternar_rota_conexao, icon='swap_horiz').props('outline color=purple-700')
                            ui.button('Zerar Contadores do Dia', on_click=zerar_contadores_dia, icon='restart_alt').props('outline color=slate-700')

        # --- LOOP REATIVO DE ATUALIZAÇÃO (1 SEGUNDO) ---
        def atualizar_tela():
            global mqtt_client
            agora_hm = datetime.now().strftime("%H:%M")
            data_hm = datetime.now().strftime("%Y-%m-%d %H:%M")

            # Fallback silencioso se a primeira rota estiver bloqueada
            if not estado['mqtt_conectado']:
                estado['tentativas_tcp'] += 1
                if estado['tentativas_tcp'] == 5 and estado['modo_transporte'] == 'TCP:1883':
                    mqtt_client = configurar_mqtt(usar_websockets=True)
            else:
                estado['tentativas_tcp'] = 0

            # Disparo automático agendado
            for ag in horarios:
                chave = f"{data_hm}_{ag['pet']}"
                if ag['hora'] == agora_hm and chave not in disparados_minuto:
                    disparados_minuto.add(chave)
                    enviar_comando_alimentar(ag['pet'], f"Agendado {agora_hm}")

            # Badges de Status Limpos no Cabeçalho
            if estado['mqtt_conectado']:
                conn_badge.set_text('Nuvem Online')
                conn_badge.props('color=green')
            else:
                conn_badge.set_text('Reconectando...')
                conn_badge.props('color=amber')

            if estado['comedouro_online']:
                comedouro_badge.set_text('Comedouro Online')
                comedouro_badge.props('color=emerald-600')
            else:
                comedouro_badge.set_text('Comedouro Offline')
                comedouro_badge.props('color=amber-700')

            # Atualiza Estoque (% e Gramas)
            pct = estado['pct']
            estoque_pct_label.set_text(f"{pct}%")
            estoque_bar.set_value(round(pct / 100.0, 2))
            estoque_gramas_label.set_text(f"~{estado['estoque_g']}g disponíveis de 2.000g")

            if pct >= 60:
                estoque_badge.set_text('Abastecido')
                estoque_badge.props('color=green')
                estoque_bar.props('color=green')
            elif pct >= 25:
                estoque_badge.set_text('Nível Médio')
                estoque_badge.props('color=blue')
                estoque_bar.props('color=blue')
            elif pct >= 10:
                estoque_badge.set_text('Reabastecer')
                estoque_badge.props('color=amber')
                estoque_bar.props('color=amber')
            else:
                estoque_badge.set_text('Crítico')
                estoque_badge.props('color=red')
                estoque_bar.props('color=red')

            # Atualiza KPIs e Diagnóstico
            total_g_label.set_text(f"{estado['total_gramas_hoje']} g")
            refeicoes_sub.set_text(f"{estado['refeicoes_hoje']} refeições confirmadas")
            status_label.set_text(estado['status'])

            if "SUCESSO" in estado['status']:
                status_label.classes(replace='text-lg font-bold my-3 leading-snug text-emerald-600')
            elif "AVISO" in estado['status']:
                status_label.classes(replace='text-lg font-bold my-3 leading-snug text-amber-600')
            elif "FALHA" in estado['status'] or "ERRO" in estado['status']:
                status_label.classes(replace='text-lg font-bold my-3 leading-snug text-red-600')
            else:
                status_label.classes(replace='text-lg font-bold my-3 leading-snug text-slate-800')

            # Atualiza Resumo de Rotinas
            resumo_rotinas_container.clear()
            with resumo_rotinas_container:
                if not horarios:
                    ui.label('Nenhuma rotina ativa.').classes('text-xs text-slate-400')
                else:
                    for item in horarios:
                        g_pet = pets.get(item['pet'], {}).get('gramas', '--')
                        with ui.row().classes('items-center gap-2 bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg'):
                            ui.label(item['hora']).classes('text-xs font-mono font-bold text-blue-700')
                            ui.label(f"{item['pet']} ({g_pet}g)").classes('text-xs font-medium text-slate-700')

            qtd_visivel = min(len(pets), max_pets) if max_pets else len(pets)
            limite_txt = f" de {max_pets}" if max_pets else " (ilimitado)"
            resumo_rodape_label.set_text(f"{qtd_visivel}{limite_txt} pets ativos • {len(horarios)} rotinas programadas")

            if is_plano_tutor:
                nuvem_status_label.set_text('Conectado em Tempo Real' if estado['mqtt_conectado'] else 'Reconectando...')
                plantel_label.set_text(f"{len(pets)} animais")

            # Renderiza Logs
            def popular_lista_logs(container, limite=None):
                container.clear()
                with container:
                    lista = logs[:limite] if limite else logs
                    if not lista:
                        with ui.row().classes('w-full items-center justify-center gap-2 py-5 bg-slate-50 rounded-xl border border-dashed border-slate-200'):
                            ui.icon('inbox', color='slate-400', size='sm')
                            ui.label("Nenhuma ocorrência registrada até o momento.").classes('text-slate-400 text-xs font-medium')
                        return
                    for log in lista:
                        cor = 'green' if log['tipo'] == 'sucesso' else ('amber' if log['tipo'] == 'aviso' else 'red')
                        icone = 'check_circle' if log['tipo'] == 'sucesso' else ('warning' if log['tipo'] == 'aviso' else 'error')
                        with ui.row().classes('w-full justify-between items-center py-2.5 border-b border-slate-100 px-2'):
                            with ui.row().classes('items-center gap-3'):
                                ui.icon(icone, color=cor, size='sm')
                                ui.label(log['msg']).classes(f'font-medium text-sm text-{cor}-700')
                            ui.label(log['hora']).classes('text-xs text-slate-400 font-mono')

            popular_lista_logs(mini_log_container, limite=3)
            popular_lista_logs(log_container, limite=None)

        ui.timer(1.0, atualizar_tela)

ui.run(title='PetDose • Nutrição Inteligente', port=8080, storage_secret='petdose_uema_2026_secret')