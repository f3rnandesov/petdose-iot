#include <WiFi.h>
#include <PubSubClient.h>
#include <ESP32Servo.h>
#include <ArduinoJson.h>

// ============================================================================
// PetDose - versão SEM balança (dosagem por tempo calibrado)
//
// O nível do reservatório vem SEMPRE do sensor ultrassônico HC-SR04.
//
// A porção é servida abrindo a comporta em pulsos. O total servido é uma
// ESTIMATIVA pelo tempo de abertura x VAZAO_G_POR_S (ver calibração no README).
// ============================================================================

// ------------------------- CONFIGURAÇÃO PRINCIPAL ---------------------------
// Wi-Fi da bancada (dica: use o roteador do celular, redes de faculdade
// costumam bloquear a porta 1883 do MQTT)
const char* ssid     = "Wokwi-GUEST";
const char* password = "";  
// No Wokwi use: ssid = "Wokwi-GUEST", password = ""

const char* mqtt_server = "broker.emqx.io";

// --- PINAGEM ---
const int SERVO_PIN  = 18;
const int TRIG_PIN   = 5;
const int ECHO_PIN   = 19;   // ATENÇÃO: ECHO do HC-SR04 é 5 V -> usar divisor de tensão
const int BOTAO_PIN  = 4;    // botão entre GPIO4 e GND

// --- CALIBRAÇÃO DO RESERVATÓRIO (medir no SEU recipiente, ver README) ---
const float DIST_CHEIO_CM     = 4.0;   // distância sensor -> ração com o pote cheio
const float DIST_VAZIO_CM     = 24.0;  // distância sensor -> fundo com o pote vazio
const int   CAPACIDADE_SILO_G = 2000;  // quanto de ração cabe com o pote cheio

// --- CALIBRAÇÃO DA DOSAGEM ---
const float VAZAO_G_POR_S            = 25.0;  // gramas por segundo de comporta aberta
const unsigned long PULSO_ABERTO_MS  = 1000;  // tempo aberto por pulso
const unsigned long PULSO_FECHADO_MS = 300;   // pausa entre pulsos (evita travar)
// Tipo de servo:
//   true  -> servo de ROTAÇÃO CONTÍNUA (360°): gira enquanto serve e para depois
//   false -> servo comum (180°): vai até um ângulo para abrir e volta para fechar
const bool SERVO_360 = true;

// Servo 360°: 90 = parado; quanto mais longe de 90, mais rápido
// (ex.: 180 = rápido num sentido, 0 = rápido no outro, 120 = devagar)
const int SERVO_360_VELOCIDADE = 180;

// Servo 180°: ângulos da comporta (ajuste conforme a montagem)
const int SERVO_FECHADO = 0;
const int SERVO_ABERTO  = 90;
// ----------------------------------------------------------------------------

const char* topic_comando     = "petdose/uema/comando";
const char* topic_config      = "petdose/uema/config";
const char* topic_ping        = "petdose/uema/ping";
const char* topic_status      = "petdose/uema/status";
const char* topic_nivel       = "petdose/uema/nivel";

WiFiClient espClient;
PubSubClient client(espClient);
Servo meuServo;

String petAtivoNome   = "Thor";
int    petAtivoGramas = 250;

unsigned long ultimoAcionamento = 0;
const unsigned long COOLDOWN_MS = 10000;

// Comando recebido via MQTT é executado no loop(), fora do callback
bool   comandoPendente = false;
String comandoPet      = "";
int    comandoGramas   = 0;

// ============================================================================
// SENSOR ULTRASSÔNICO
// ============================================================================

// Uma leitura em cm, ou -1 se o sensor não respondeu
float lerDistanciaUnicaCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  long duracao = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duracao == 0) return -1;
  return duracao * 0.0343 / 2.0;
}

// Mediana de 7 leituras: elimina picos causados pela superfície irregular
// da ração. Retorna -1 se a maioria das leituras falhou.
float lerDistanciaCm() {
  const int N = 7;
  float v[N];
  int validas = 0;
  for (int i = 0; i < N; i++) {
    float d = lerDistanciaUnicaCm();
    if (d > 0) v[validas++] = d;
    delay(30);  // o HC-SR04 precisa de ~30 ms entre medições
  }
  if (validas < 3) return -1;

  for (int i = 1; i < validas; i++) {  // ordena (insertion sort)
    float x = v[i];
    int j = i - 1;
    while (j >= 0 && v[j] > x) { v[j + 1] = v[j]; j--; }
    v[j + 1] = x;
  }
  return v[validas / 2];
}

// Estoque em gramas, ou -1 se o sensor falhou
int lerEstoqueGramas() {
  float dist = lerDistanciaCm();
  if (dist < 0) return -1;
  float d = constrain(dist, DIST_CHEIO_CM, DIST_VAZIO_CM);
  float fracao = (DIST_VAZIO_CM - d) / (DIST_VAZIO_CM - DIST_CHEIO_CM);
  return (int)(fracao * CAPACIDADE_SILO_G + 0.5);
}

bool sensorEmFalha = false;

void publicarNivelSilo() {
  int estoque_g = lerEstoqueGramas();
  if (estoque_g < 0) {
    Serial.println("Sensor de nivel sem resposta (verifique fios do HC-SR04)");
    if (!sensorEmFalha) {  // avisa o dashboard só uma vez, não a cada 5 s
      client.publish(topic_status, "ERRO: Sensor de nivel sem resposta");
      sensorEmFalha = true;
    }
    return;
  }
  if (sensorEmFalha) {
    sensorEmFalha = false;
    client.publish(topic_status, "PONG");  // volta o status para "Pronto para servir"
  }
  int pct = (estoque_g * 100) / CAPACIDADE_SILO_G;

  StaticJsonDocument<128> doc;
  doc["pct"] = pct;
  doc["estoque_g"] = estoque_g;

  char buffer[128];
  serializeJson(doc, buffer);
  client.publish(topic_nivel, buffer);
}

// ============================================================================
// DISPENSADOR
// ============================================================================

// Espera sem derrubar a conexão MQTT
void esperarMantendoMqtt(unsigned long ms) {
  unsigned long inicio = millis();
  while (millis() - inicio < ms) {
    client.loop();
    delay(10);
  }
}

// Abre a comporta (servo 180°) ou começa a girar (servo 360°)
void ligarServo() {
  if (!meuServo.attached()) meuServo.attach(SERVO_PIN, 500, 2400);
  meuServo.write(SERVO_360 ? SERVO_360_VELOCIDADE : SERVO_ABERTO);
}

// Fecha/para e corta o sinal do servo. Sem sinal, o servo 360° para de vez
// (mesmo que o "90" dele não seja exatamente o ponto de parada) e o servo
// 180° para de tremer em repouso.
void desligarServo() {
  if (SERVO_360) {
    meuServo.write(90);
    esperarMantendoMqtt(50);
  } else {
    meuServo.write(SERVO_FECHADO);
    esperarMantendoMqtt(400);  // tempo para a comporta chegar ao fechado
  }
  meuServo.detach();
  pinMode(SERVO_PIN, OUTPUT);
  digitalWrite(SERVO_PIN, LOW);
}

void acionarDispensador(String nomePet, int metaGramas) {
  if (ultimoAcionamento != 0 && (millis() - ultimoAcionamento < COOLDOWN_MS)) {
    client.publish(topic_status, "AVISO: Comando duplicado bloqueado");
    return;
  }
  ultimoAcionamento = millis();

  int estoque_g = lerEstoqueGramas();
  if (estoque_g < 0) {
    client.publish(topic_status, "ERRO: Sensor de nivel sem resposta, porcao nao servida");
    return;
  }
  if (estoque_g < metaGramas) {
    String msgErro = "ERRO: Estoque insuficiente para " + nomePet +
                     " (precisa " + String(metaGramas) + "g, disponivel ~" + String(estoque_g) + "g)";
    Serial.println(msgErro);
    client.publish(topic_status, msgErro.c_str());
    return;
  }

  unsigned long tempoTotalMs = (unsigned long)((metaGramas / VAZAO_G_POR_S) * 1000.0);

  Serial.println("Servindo ~" + String(metaGramas) + "g para " + nomePet +
                 " (" + String(tempoTotalMs) + " ms de abertura)");

  unsigned long tempoAbertoMs = 0;
  while (tempoAbertoMs < tempoTotalMs) {
    unsigned long pulso = min(PULSO_ABERTO_MS, tempoTotalMs - tempoAbertoMs);
    ligarServo();
    esperarMantendoMqtt(pulso);
    desligarServo();
    tempoAbertoMs += pulso;
    if (tempoAbertoMs < tempoTotalMs) esperarMantendoMqtt(PULSO_FECHADO_MS);
  }

  int servidoEstimado = (int)(tempoAbertoMs / 1000.0 * VAZAO_G_POR_S + 0.5);

  String msgSucesso = "SUCESSO: " + String(servidoEstimado) + "g servidos para " + nomePet;
  Serial.println(msgSucesso);
  client.publish(topic_status, msgSucesso.c_str());

  esperarMantendoMqtt(500);  // deixa a ração assentar antes de medir o nível
  publicarNivelSilo();
}

// ============================================================================
// MQTT
// ============================================================================

void callback(char* topic, byte* payload, unsigned int length) {
  String mensagem = "";
  for (unsigned int i = 0; i < length; i++) {
    mensagem += (char)payload[i];
  }
  String topicoStr = String(topic);

  if (topicoStr == topic_ping) {
    client.publish(topic_status, "PONG");
    publicarNivelSilo();
    return;
  }

  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, mensagem)) return;

  if (topicoStr == topic_config) {
    petAtivoNome   = doc["pet"] | "Thor";
    petAtivoGramas = doc["gramas"] | 250;
    Serial.println("Pet ativo sincronizado: " + petAtivoNome + " (" + String(petAtivoGramas) + "g)");
  }
  else if (topicoStr == topic_comando) {
    comandoPet      = doc["pet"] | petAtivoNome;
    comandoGramas   = doc["gramas"] | petAtivoGramas;
    comandoPendente = true;
  }
}

void conectarWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  Serial.print("Conectando ao Wi-Fi \"" + String(ssid) + "\"");
  int tentativas = 0;
  while (WiFi.status() != WL_CONNECTED && tentativas < 40) {  // ~20 s
    delay(500);
    Serial.print(".");
    tentativas++;
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nFalha no Wi-Fi, reiniciando...");
    ESP.restart();
  }
  Serial.println("\nWiFi Conectado! IP: " + WiFi.localIP().toString());
}

void reconectar() {
  if (WiFi.status() != WL_CONNECTED) conectarWiFi();

  while (!client.connected()) {
    String clientId = "PetDose_ESP32_" + String(random(0xffff), HEX);
    Serial.print("Conectando ao MQTT...");
    if (client.connect(clientId.c_str())) {
      Serial.println(" ok!");
      client.subscribe(topic_comando);
      client.subscribe(topic_config);
      client.subscribe(topic_ping);
      client.publish(topic_status, "PONG");
      publicarNivelSilo();
    } else {
      Serial.println(" falhou (rc=" + String(client.state()) + "), tentando em 3 s");
      delay(3000);
    }
  }
}

// ============================================================================
// SETUP / LOOP
// ============================================================================

void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(BOTAO_PIN, INPUT_PULLUP);

  meuServo.setPeriodHertz(50);
  pinMode(SERVO_PIN, OUTPUT);
  digitalWrite(SERVO_PIN, LOW);  // sem pulso = servo parado
  if (!SERVO_360) {
    // servo comum: garante a comporta fechada ao ligar
    ligarServo();
    desligarServo();
  }

  conectarWiFi();
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);
}

void loop() {
  if (!client.connected()) {
    reconectar();
  }
  client.loop();

  if (comandoPendente) {
    comandoPendente = false;
    acionarDispensador(comandoPet, comandoGramas);
  }

  // Botão físico com debounce simples
  if (digitalRead(BOTAO_PIN) == LOW) {
    delay(50);
    if (digitalRead(BOTAO_PIN) == LOW) {
      acionarDispensador(petAtivoNome, petAtivoGramas);
      while (digitalRead(BOTAO_PIN) == LOW) client.loop();  // espera soltar
    }
  }

  static unsigned long ultimoEnvio = 0;
  if (millis() - ultimoEnvio > 5000) {
    float d = lerDistanciaCm();
    int est = lerEstoqueGramas();
    String aviso = "";
    if (d > 0 && d <= DIST_CHEIO_CM) aviso = "  <- abaixo de DIST_CHEIO_CM, travado em 100%";
    if (d >= DIST_VAZIO_CM)          aviso = "  <- acima de DIST_VAZIO_CM, travado em 0%";
    Serial.println("[calibracao] distancia = " + String(d, 1) + " cm | estoque = " +
                   String(est) + " g (" + String(est * 100 / CAPACIDADE_SILO_G) + "%)" + aviso);
    publicarNivelSilo();
    ultimoEnvio = millis();
  }
}
