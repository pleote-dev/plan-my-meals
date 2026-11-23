<p align="center">
  <img src="icon.png" alt="Plan My Meals" width="128" />
</p>

<p align="center">
  🌐 <a href="README.md">English</a> | <strong>Português</strong>
</p>

# Plan My Meals para Home Assistant

[![Abrir repositório no HACS do teu Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pleote-dev&repository=plan-my-meals&category=integration)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Integração autónoma para **Home Assistant** dedicada ao planeamento semanal de refeições, gestão da biblioteca de receitas, suporte nativo para IA do Home Assistant, integração com agentes de IA externos (ex.: Hermes / OpenJarvis / MCP) e **pesquisa de preços de supermercados** (Continente, Auchan, Pingo Doce, Aldi, Lidl, Intermarché, Minipreço, El Corte Inglés, Mercadona).

---

## Funcionalidades

- **Integração 100% Nativa no Home Assistant (sem precisar de Pyscript):** instala via HACS com configuração completa por interface (**Config Flow & Options Flow**).
- **Aplicação Web Embutida e Painel na Barra Lateral:** serve automaticamente a interface interativa do Plan My Meals na barra lateral do Home Assistant (sem configuração manual em `/config/www/`).
- **Preparada para Múltiplos Idiomas (Português e Inglês incluídos):** deteta automaticamente o idioma do Home Assistant, inclui seletor de idioma na barra superior e utiliza ficheiros JSON simples para facilitar novas traduções.
- **36 Receitas Base Sem Direitos de Autor:** refeições principais, pequenos-almoços e sobremesas com ingredientes estruturados, valores nutricionais e ilustrações originais sob licença MIT (ver `ATTRIBUTIONS.md`).
- **Gerador Semanal Inteligente:** 80% favoritas (4–5★), 20% receitas novas/sem avaliação, exclui 1–3★, evita repetir categorias no mesmo dia e preserva refeições fixadas.
- **Preços de Supermercado e Custo da Ementa:**
  - Acompanha os principais supermercados em Portugal (Continente, Auchan, Pingo Doce / Mercadão, Aldi, Lidl, Intermarché, Minipreço, El Corte Inglés, Mercadona; extensível a outros países).
  - Calcula o **custo médio por refeição**, **custo médio semanal** e **custo por pessoa**.
  - Anota os itens da lista de compras com quantidade + melhor preço e supermercado, ex.: **`Ovomaltine (2 un) (9€ Auchan)`**, e guarda ligações diretas para a loja.
- **IA Nativa do Home Assistant + Agentes Externos:**
  - Funciona com qualquer entidade `ai_task.*` ou `conversation.*` do Home Assistant (Google Generative AI, OpenAI, Anthropic, Ollama, etc.).
  - Geração resiliente em duas fases (estruturada + fallback JSON), timeouts alargados (60s cloud / 90s modelos locais), redundância com IA alternativa e registo detalhado nos logs do Home Assistant.
  - Expõe serviços completos (`plan_my_meals.*`) com `return_response` para que agentes externos como o **Hermes** possam ler/alterar planos, adicionar receitas, avaliar pratos e sincronizar listas de compras.
- **Entidades Expostas para Dashboards e Automações:**
  - `sensor.plan_my_meals_lunch_today` e `sensor.plan_my_meals_dinner_today` (com imagem, tempo, método, avaliação, custo médio e ingredientes)
  - `sensor.plan_my_meals_week_cost` (custo médio semanal, custo por pessoa e detalhe diário)
  - `sensor.plan_my_meals_missing_ingredients` (contagem de faltantes + itens com melhor preço, loja e link direto)
  - `sensor.plan_my_meals_recipes`
  - `calendar.plan_my_meals` (almoços e jantares semanais no Calendário do Home Assistant)
  - `button.plan_my_meals_generate_week`, `button.plan_my_meals_sync_shopping_list`, `button.plan_my_meals_refresh_prices`
- **Migração Automática:** se existir `/config/www/plan_my_meals_state.json` de uma instalação anterior em Pyscript, todas as receitas, variantes, avaliações, planos semanais e imagens locais são importados automaticamente no primeiro arranque.

---

## Instalação via HACS

### Com 1 Clique (My Home Assistant)

[![Abrir repositório no HACS do teu Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pleote-dev&repository=plan-my-meals&category=integration)

### Instalação Manual no HACS

1. Abre o **HACS** → **Integrações** → menu (`⋮`) → **Repositórios personalizados**.
2. Adiciona `https://github.com/pleote-dev/plan-my-meals` com a categoria **Integração**.
3. Pesquisa por **Plan My Meals** e clica em **Transferir**.
4. Reinicia o Home Assistant.
5. Vai a **Definições → Dispositivos e Serviços → Adicionar Integração → Plan My Meals** e configura a lista de compras (`todo.*`), número de pessoas, equipamentos de cozinha, entidade de IA e supermercados.

---

## Serviços (Automações & Agentes de IA Externos)

| Serviço | Descrição |
|---|---|
| `plan_my_meals.get_plan` | Devolve o plano atual, receitas, ingredientes em falta e custos |
| `plan_my_meals.generate_week` | Gera um novo plano semanal |
| `plan_my_meals.swap_meal` | Substitui o almoço ou jantar de um dia específico (`0`..`6`) |
| `plan_my_meals.upsert_recipe` | Cria ou atualiza uma receita ou variante |
| `plan_my_meals.delete_recipe` | Apaga uma receita e as suas variantes |
| `plan_my_meals.rate_recipe` | Define avaliação de 1–5★ (`0` limpa) |
| `plan_my_meals.check_similarity` | Verifica se existem receitas duplicadas ou candidatas a variante |
| `plan_my_meals.generate_recipe_ai` | Gera ou completa uma receita com IA do HA (fallback estruturado/JSON + logs) |
| `plan_my_meals.upload_image` | Guarda imagem em base64 ou transfere URL localmente |
| `plan_my_meals.sync_shopping_list` | Envia ingredientes em falta (`Ovomaltine (2 un) (9€ Auchan)`) para `todo.*` |
| `plan_my_meals.refresh_prices` | Atualiza preços de supermercado para a semana atual (ou todas as receitas) |
| `plan_my_meals.set_ingredient_price` | Define ou substitui manualmente o preço e URL de um ingrediente |

---

## Automação Diária de Atualização de Preços

Podes agendar o Home Assistant para atualizar os preços dos supermercados automaticamente uma vez por dia. A data/hora da última execução e o número de preços obtidos aparecem no menu **Compras → Opções** da aplicação (junto com o botão **Correr pesquisa agora** e o modo de pesquisa com IA).

Adiciona esta automação ao teu `automations.yaml` (ou cria-a em **Definições → Automações e Cenas**):

```yaml
alias: "Plan My Meals - Atualização Diária de Preços"
description: "Atualizar preços dos supermercados locais para os ingredientes do plano semanal"
mode: single
triggers:
  - trigger: time
    at: "07:00:00"
conditions: []
actions:
  - action: plan_my_meals.refresh_prices
    data:
      all_recipes: false
      max_items: 25
```

- Define `all_recipes: true` se quiseres atualizar preços para toda a biblioteca de receitas em vez de apenas o plano semanal atual.
- Opcionalmente, podes passar `use_ai: true` (ou `false`) para substituir o modo configurado em **Compras → Opções**.

---

## Traduções & Como Adicionar um Novo Idioma

O Plan My Meals foi preparado para ser facilmente traduzido para qualquer idioma:

1. **Interface da Aplicação Web:**
   - Copia `custom_components/plan_my_meals/frontend/locales/en.json` (ou `pt.json`) para `<idioma>.json` (ex.: `es.json`, `fr.json`, `de.json`) e traduz os textos (mantendo intactas as variáveis entre `{chavetas}`).
   - Regista o novo idioma em `custom_components/plan_my_meals/frontend/locales/index.json`.
   - Qualquer chave em falta usa automaticamente o inglês como fallback.
2. **Configuração e Entidades do Home Assistant:**
   - Copia `custom_components/plan_my_meals/translations/en.json` para `custom_components/plan_my_meals/translations/<idioma>.json` e traduz as etiquetas.
3. Abre um Pull Request — contribuições são muito bem-vindas!
