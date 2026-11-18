#include <WiFi.h>
#include <PubSubClient.h>
#include <ESP32Servo.h>
#include <HX711.h>
#include <ArduinoJson.h>

// --- PINAGEM ---
const int SERVO_PIN  = 18;
const int TRIG_PIN   = 5;
const int ECHO_PIN   = 19;
const int HX711_DT   = 21;
const int HX711_SCK  = 22;
const int BOTAO_PIN  = 4;

// --- REDE E MQTT (MESMO BROKER DO DASHBOARD) ---
const char* ssid        = "Wokwi-GUEST";
const char* password    = "";
const char* mqtt_server = "broker.emqx.io";

const char* topic_comando = "petdose/uema/comando";
const char* topic_config  = "petdose/uema/config";
const char* topic_ping    = "petdose/uema/ping";
const char* topic_status  = "petdose/uema/status";
const char* topic_nivel   = "petdose/uema/nivel";

// --- CALIBRAÇÃO ---
const int DIST_CHEIO_CM     = 4;     // 100% cheio
const int DIST_VAZIO_CM     = 24;    // 0% vazio
const int CAPACIDADE_SILO_G = 2000;  // 2 kg
const float FATOR_BALANCA   = 0.42;  // Leitura direta em gramas no Wokwi

WiFiClient espClient;
PubSubClient client(espClient);
Servo meuServo;
HX711 balanca;

String petAtivoNome   = "Thor";
int    petAtivoGramas = 250;

unsigned long ultimoAcionamento = 0;
const unsigned long COOLDOWN_MS = 10000;

long lerDistanciaCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  long duracao = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duracao == 0) return DIST_VAZIO_CM;
  return duracao * 0.034 / 2;
}

int calcularPercentualSilo(long dist) {
  long d = constrain(dist, DIST_CHEIO_CM, DIST_VAZIO_CM);
  return map(d, DIST_VAZIO_CM, DIST_CHEIO_CM, 0, 100);
}

int calcularEstoqueGramas(int percentual) {
  return (percentual * CAPACIDADE_SILO_G) / 100;
}

void publicarNivelSilo() {
  long dist = lerDistanciaCm();
  int pct = calcularPercentualSilo(dist);
  int estoque_g = calcularEstoqueGramas(pct);

  StaticJsonDocument<128> doc;
  doc["pct"] = pct;
  doc["estoque_g"] = estoque_g;

  char buffer[128];
  serializeJson(doc, buffer);
  client.publish(topic_nivel, buffer);
}

void acionarDispensador(String nomePet, int metaGramas) {
  if (ultimoAcionamento != 0 && (millis() - ultimoAcionamento < COOLDOWN_MS)) {
    client.publish(topic_status, "AVISO: Comando duplicado bloqueado");
    return;
  }
  ultimoAcionamento = millis();

  long dist = lerDistanciaCm();
  int pct = calcularPercentualSilo(dist);
  int estoque_g = calcularEstoqueGramas(pct);

  if (estoque_g < metaGramas) {
    String msgErro = "ERRO: Estoque insuficiente para " + nomePet +
                     " (precisa " + String(metaGramas) + "g, disponivel ~" + String(estoque_g) + "g)";
    Serial.println(msgErro);
    client.publish(topic_status, msgErro.c_str());
    return;
  }

  Serial.println("Tarando balanca e servindo " + String(metaGramas) + "g para " + nomePet);
  balanca.tare();
  delay(200);
  meuServo.write(90);

  unsigned long inicioDispensacao = millis();
  const unsigned long TIMEOUT_OBSTRUCAO_MS = 10000;
  float pesoAtual = 0;

  while (pesoAtual < metaGramas) {
    client.loop();
    pesoAtual = balanca.get_units(2);
    if (pesoAtual < 0) pesoAtual = 0;

    if (millis() - inicioDispensacao > TIMEOUT_OBSTRUCAO_MS) {
      meuServo.write(0);
      String msgFalha = "FALHA: Obstrucao ou falta de fluxo para " + nomePet +
                        " (servido " + String((int)pesoAtual) + "g de " + String(metaGramas) + "g)";
      Serial.println(msgFalha);
      client.publish(topic_status, msgFalha.c_str());
      publicarNivelSilo();
      return;
    }
    delay(150);
  }

  meuServo.write(0);
  String msgSucesso = "SUCESSO: " + String((int)pesoAtual) + "g servidos para " + nomePet;
  Serial.println(msgSucesso);
  client.publish(topic_status, msgSucesso.c_str());
  publicarNivelSilo();
}

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
  DeserializationError erro = deserializeJson(doc, mensagem);
  if (erro) return;

  if (topicoStr == topic_config) {
    petAtivoNome   = doc["pet"] | "Thor";
    petAtivoGramas = doc["gramas"] | 250;
    Serial.println("Pet ativo sincronizado: " + petAtivoNome + " (" + String(petAtivoGramas) + "g)");
  }
  else if (topicoStr == topic_comando) {
    String pet    = doc["pet"] | petAtivoNome;
    int gramas    = doc["gramas"] | petAtivoGramas;
    acionarDispensador(pet, gramas);
  }
}

void reconectar() {
  while (!client.connected()) {
    String clientId = "PetDose_ESP32_" + String(random(0xffff), HEX);
    if (client.connect(clientId.c_str())) {
      Serial.println("MQTT Conectado em broker.emqx.io!");
      client.subscribe(topic_comando);
      client.subscribe(topic_config);
      client.subscribe(topic_ping);
      client.publish(topic_status, "PONG");
      publicarNivelSilo();
    } else {
      delay(3000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(BOTAO_PIN, INPUT_PULLUP);

  meuServo.attach(SERVO_PIN);
  meuServo.write(0);

  balanca.begin(HX711_DT, HX711_SCK);
  balanca.set_scale(FATOR_BALANCA);
  balanca.tare();

  WiFi.disconnect(true);
  delay(100);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password, 6);

  Serial.print("Conectando ao Wi-Fi");
  int tentativas = 0;
  while (WiFi.status() != WL_CONNECTED && tentativas < 20) {
    delay(500);
    Serial.print(".");
    tentativas++;
  }

  if (WiFi.status() != WL_CONNECTED) {
    ESP.restart();
  }

  Serial.println("\nWiFi Conectado!");
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);
}

void loop() {
  if (!client.connected()) {
    reconectar();
  }
  client.loop();

  if (digitalRead(BOTAO_PIN) == LOW) {
    acionarDispensador(petAtivoNome, petAtivoGramas);
    delay(400);
  }

  static unsigned long ultimoEnvio = 0;
  if (millis() - ultimoEnvio > 5000) {
    publicarNivelSilo();
    ultimoEnvio = millis();
  }
}