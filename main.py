import concurrent.futures
import io
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

load_dotenv()

DB_PATH = "scopeo.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def extract_file_text(filename: str, content: bytes) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        if PdfReader is None:
            return "[PDF anexado. Instale pypdf para leitura automática completa.]"
        try:
            reader = PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            extracted = "\n".join(pages).strip()
            return extracted if extracted else "[PDF sem camada de texto selecionável.]"
        except Exception as e:
            return f"[Não foi possível ler o PDF: {e}]"
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1", errors="ignore")


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            client_name TEXT NOT NULL,
            start_date TEXT NOT NULL,
            due_date TEXT NOT NULL,
            deadline_days INTEGER NOT NULL,
            contract_value REAL NOT NULL,
            estimated_hours REAL NOT NULL,
            hourly_rate REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'Em andamento',
            scope_objectives TEXT NOT NULL,
            scope_deliverables TEXT NOT NULL,
            scope_included TEXT NOT NULL,
            scope_excluded TEXT NOT NULL,
            payment_terms TEXT NOT NULL,
            contract_filename TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            meeting_title TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'Transcrição',
            filename TEXT DEFAULT '',
            transcript TEXT NOT NULL,
            summary TEXT NOT NULL,
            addendum_proposal TEXT NOT NULL,
            extra_hours REAL NOT NULL,
            extra_cost REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            requirement TEXT NOT NULL,
            contracted_item TEXT NOT NULL,
            contract_excerpt TEXT NOT NULL,
            evidence_quote TEXT NOT NULL,
            status TEXT NOT NULL,
            needs_human_review INTEGER NOT NULL DEFAULT 0,
            confidence INTEGER NOT NULL DEFAULT 92,
            category TEXT NOT NULL DEFAULT 'Funcionalidade',
            justification TEXT NOT NULL,
            complexity TEXT NOT NULL,
            estimated_hours REAL NOT NULL,
            delay_days INTEGER NOT NULL,
            calculated_cost REAL NOT NULL,
            recommended_charge REAL NOT NULL,
            approval_status TEXT NOT NULL DEFAULT 'AGUARDANDO',
            decision_note TEXT DEFAULT '',
            decided_at TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (audit_id) REFERENCES audits (id),
            FOREIGN KEY (project_id) REFERENCES projects (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS decision_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            project_name TEXT NOT NULL,
            requirement TEXT NOT NULL,
            action TEXT NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    count = cur.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    if count == 0:
        # Projeto 1: Exemplo principal do protótipo (Empresa Alpha)
        cur.execute(
            """
            INSERT INTO projects (
                name, client_name, start_date, due_date, deadline_days,
                contract_value, estimated_hours, hourly_rate, status,
                scope_objectives, scope_deliverables, scope_included,
                scope_excluded, payment_terms, contract_filename, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Desenvolvimento de Plataforma Digital",
                "Empresa Alpha",
                "01/10/2026",
                "15/11/2026",
                45,
                25000.00,
                200.0,
                125.00,
                "Em andamento",
                "Construir portal web responsivo para autoatendimento de clientes B2B com gestão de pedidos e área administrativa.",
                "- Protótipo navegável de alta fidelidade\n- Aplicação Web Responsiva (React)\n- API REST com autenticação e banco de dados\n- Manual de operação e deploy em produção",
                "- Autenticação tradicional com e-mail e senha (Cláusula 2.1)\n- Painel administrativo com métricas de pedidos (Cláusula 2.2)\n- Catálogo de serviços e formulário de solicitação (Cláusula 2.3)\n- Exportação de relatórios simples em CSV (Cláusula 2.4)",
                "- Integração bidirecional em tempo real com ERP SAP/TOTVS (Cláusula 4.1)\n- Aplicativo mobile nativo iOS/Android (Cláusula 4.2)\n- Módulo de faturamento com emissão de NF-e (Cláusula 4.3)\n- Login social SSO / OAuth corporativo (Cláusula 4.4)",
                "40% na assinatura, 30% na entrega do MVP intermediário, 30% na homologação final. Hora técnica excedente fixada em R$ 125,00/h.",
                "Contrato_Alpha_Plataforma_2026.pdf",
                "01/10/2026 09:30",
            ),
        )
        p1 = cur.lastrowid

        cur.execute(
            """
            INSERT INTO audits (
                project_id, meeting_title, source_type, filename, transcript,
                summary, addendum_proposal, extra_hours, extra_cost, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p1,
                "Reunião de Alinhamento — Sprint 3",
                "Transcrição",
                "transcricao_sprint3_alpha.pdf",
                "Diretor Alpha: Pessoal, o painel está ficando ótimo. Para entrarmos no ar, precisamos conectar o portal direto no nosso ERP SAP para baixar estoque automático, colocar login corporativo via Microsoft SSO e gerar relatórios executivos em PDF personalizado com gráficos. Também queremos ajustar a cor do cabeçalho para o nosso novo guia de marca.",
                "Foram identificadas 4 demandas na reunião da Sprint 3: duas explicitamente fora do escopo (ERP SAP e SSO), uma alteração de escopo (relatórios em PDF customizado) e um ajuste visual coberto pelo contrato.",
                "Olá equipe Empresa Alpha! Consolidamos as solicitações da Sprint 3. As integrações com ERP SAP (24h), Login SSO Microsoft (10h) e geração de PDFs customizados (8h) excedem o escopo original (Cláusulas 4.1, 4.4 e 2.4). O custo adicional estimado é de R$ 5.250,00 (42h técnicas, +6 dias úteis), com valor recomendado de aditivo em R$ 6.037,50. Podemos formalizar o termo aditivo antes de iniciar o desenvolvimento?",
                42.0,
                5250.00,
                "12/11/2026 15:20",
            ),
        )
        a1 = cur.lastrowid

        cur.executemany(
            """
            INSERT INTO audit_items (
                audit_id, project_id, requirement, contracted_item, contract_excerpt,
                evidence_quote, status, needs_human_review, confidence, category,
                justification, complexity, estimated_hours, delay_days,
                calculated_cost, recommended_charge, approval_status, decision_note, decided_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    a1, p1,
                    "Integração em tempo real com ERP SAP",
                    "Catálogo de serviços e gestão interna de pedidos",
                    "Cláusula 4.1: Fica expressamente excluída integração bidirecional em tempo real com ERPs externos (SAP/TOTVS).",
                    "precisamos conectar o portal direto no nosso ERP SAP para baixar estoque automático",
                    "FORA_DO_ESCOPO", 0, 98, "Integração",
                    "Excluído explicitamente pela Cláusula 4.1 do contrato original.",
                    "ALTA", 24.0, 4, 3000.00, 3450.00, "AGUARDANDO", "", "", "12/11/2026 15:20",
                ),
                (
                    a1, p1,
                    "Autenticação Corporativa Microsoft SSO",
                    "Autenticação tradicional com e-mail e senha",
                    "Cláusula 2.1 / 4.4: Acesso via e-mail e senha; login social ou SSO corporativo não está contemplado.",
                    "colocar login corporativo via Microsoft SSO",
                    "FORA_DO_ESCOPO", 0, 96, "Segurança",
                    "Conflita diretamente com a Cláusula 4.4 de exclusões contratuais.",
                    "MEDIA", 10.0, 1, 1250.00, 1437.50, "AGUARDANDO", "", "", "12/11/2026 15:20",
                ),
                (
                    a1, p1,
                    "Exportação de Relatórios Executivos em PDF com Gráficos",
                    "Exportação de relatórios simples em CSV",
                    "Cláusula 2.4: O sistema permitirá a exportação de tabelas consolidadas exclusivamente em formato CSV.",
                    "gerar relatórios executivos em PDF personalizado com gráficos",
                    "ALTERACAO_DE_ESCOPO", 1, 79, "Relatórios",
                    "O contrato prevê exportação em CSV, mas não diagramação visual em PDF. Recomenda-se validação comercial.",
                    "MEDIA", 8.0, 1, 1000.00, 1150.00, "EM_REVISAO", "Verificar se entra como bonificação ou aditivo.", "13/11/2026 10:15", "12/11/2026 15:20",
                ),
                (
                    a1, p1,
                    "Ajuste de cor do cabeçalho conforme manual de marca",
                    "Protótipo e aplicação visual responsiva",
                    "Cláusula 2.2: Interface alinhada à identidade visual fornecida pela contratante.",
                    "ajustar a cor do cabeçalho para o nosso novo guia de marca",
                    "DENTRO_DO_ESCOPO", 0, 95, "Interface/UX",
                    "Refinamento visual simples coberto pelo escopo contratado.",
                    "BAIXA", 0.0, 0, 0.00, 0.00, "APROVADA", "Liberado diretamente para o time de front-end.", "12/11/2026 17:00", "12/11/2026 15:20",
                ),
            ],
        )

        # Projeto 2: Clínica FisioVida
        cur.execute(
            """
            INSERT INTO projects (
                name, client_name, start_date, due_date, deadline_days,
                contract_value, estimated_hours, hourly_rate, status,
                scope_objectives, scope_deliverables, scope_included,
                scope_excluded, payment_terms, contract_filename, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Plataforma FisioCare Gestão",
                "Clínica FisioVida",
                "15/10/2026",
                "30/11/2026",
                45,
                14400.00,
                160.0,
                90.00,
                "Em andamento",
                "Digitalizar prontuários de fisioterapia e organizar agenda clínica interna.",
                "- Sistema Web de Prontuário e Agenda\n- Treinamento da recepção",
                "- Cadastro de pacientes e fisioterapeutas com e-mail e senha\n- Agenda web interna\n- Prontuário eletrônico em texto\n- Dashboard de contagem de atendimentos",
                "- Integração com WhatsApp Business API ou envio automático de SMS\n- Emissão de NF-e\n- Aplicativo mobile nativo\n- Login social (Google/Apple)",
                "50% na assinatura e 50% na entrega final. Hora adicional: R$ 90,00/h.",
                "Contrato_FisioVida_2026.pdf",
                "15/10/2026 14:00",
            ),
        )
        p2 = cur.lastrowid

        cur.execute(
            """
            INSERT INTO audits (
                project_id, meeting_title, source_type, filename, transcript,
                summary, addendum_proposal, extra_hours, extra_cost, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p2,
                "Checkpoint Quinzenal — Agenda & Lembretes",
                "Ata",
                "ata_fisiovida_0411.txt",
                "Coordenação FisioVida: A agenda ficou muito intuitiva! Agora gostaríamos que o sistema disparasse lembrete automático no WhatsApp 24h antes da sessão e liberasse emissão de recibo/NF-e direto no financeiro.",
                "Identificadas duas solicitações fora do contrato original (disparo automático WhatsApp e emissão de NF-e), totalizando 26h adicionais.",
                "Olá equipe Clínica FisioVida! Os módulos de lembrete automático via WhatsApp (14h) e emissão de NF-e (12h) não constam no contrato original. O aditivo técnico representa R$ 2.340,00 (valor comercial recomendado: R$ 2.691,00) e +4 dias no prazo.",
                26.0,
                2340.00,
                "04/11/2026 11:10",
            ),
        )
        a2 = cur.lastrowid

        cur.executemany(
            """
            INSERT INTO audit_items (
                audit_id, project_id, requirement, contracted_item, contract_excerpt,
                evidence_quote, status, needs_human_review, confidence, category,
                justification, complexity, estimated_hours, delay_days,
                calculated_cost, recommended_charge, approval_status, decision_note, decided_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    a2, p2,
                    "Disparo automático de lembretes via WhatsApp",
                    "Agenda web interna para marcação",
                    "Exclusões: Integração com WhatsApp Business API ou envio automático de SMS.",
                    "disparasse lembrete automático no WhatsApp 24h antes da sessão",
                    "FORA_DO_ESCOPO", 0, 97, "Integração",
                    "Cláusula de exclusões veta integração com WhatsApp Business API.",
                    "ALTA", 14.0, 2, 1260.00, 1449.00, "AGUARDANDO", "", "", "04/11/2026 11:10",
                ),
                (
                    a2, p2,
                    "Emissão de Nota Fiscal Eletrônica (NF-e)",
                    "Dashboard de contagem de atendimentos",
                    "Exclusões: Emissão de NF-e não contemplada na fase 1.",
                    "liberasse emissão de recibo/NF-e direto no financeiro",
                    "FORA_DO_ESCOPO", 0, 94, "Financeiro",
                    "Emissão fiscal está explicitamente fora do contrato base.",
                    "ALTA", 12.0, 2, 1080.00, 1242.00, "RECUSADA", "Cliente decidiu deixar para a Fase 2 em janeiro.", "06/11/2026 16:40", "04/11/2026 11:10",
                ),
            ],
        )

        # Projeto 3: Baixo Risco
        cur.execute(
            """
            INSERT INTO projects (
                name, client_name, start_date, due_date, deadline_days,
                contract_value, estimated_hours, hourly_rate, status,
                scope_objectives, scope_deliverables, scope_included,
                scope_excluded, payment_terms, contract_filename, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Portal B2B Distribuidora Nordeste",
                "Grupo Nordex Atacado",
                "20/10/2026",
                "20/12/2026",
                60,
                32000.00,
                320.0,
                100.00,
                "Em andamento",
                "Centralizar pedidos atacadistas de representantes comerciais com catálogo digital.",
                "- Catálogo B2B com filtros\n- Carrinho de pedidos e aprovação\n- Exportação CSV",
                "- Catálogo digital com filtros por categoria\n- Carrinho B2B com tabela fixa\n- Painel do vendedor para aprovação\n- Exportação em CSV",
                "- Gateway de pagamento com split bancário\n- Cálculo de frete via API de transportadoras\n- App mobile offline",
                "3 parcelas mensais iguais. Hora técnica adicional: R$ 100,00/h.",
                "Contrato_Nordex_B2B.pdf",
                "20/10/2026 10:00",
            ),
        )
        p3 = cur.lastrowid

        cur.execute(
            """
            INSERT INTO audits (
                project_id, meeting_title, source_type, filename, transcript,
                summary, addendum_proposal, extra_hours, extra_cost, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p3,
                "Validação de Catálogo — Sprint 1",
                "Reunião",
                "reuniao_nordex_s1.txt",
                "Gerente Nordex: Aprovamos o filtro por categoria e o fluxo do carrinho. Só gostaríamos de incluir um campo de observação no pedido antes de exportar para CSV.",
                "Solicitação pontual de campo de texto livre no pedido, enquadrada como alteração leve sem impacto financeiro relevante.",
                "Olá equipe Grupo Nordex! A inclusão do campo de observação no pedido foi enquadrada dentro dos ajustes menores previstos na Sprint 1, sem custo adicional.",
                3.0,
                300.00,
                "08/11/2026 16:00",
            ),
        )
        a3 = cur.lastrowid

        cur.execute(
            """
            INSERT INTO audit_items (
                audit_id, project_id, requirement, contracted_item, contract_excerpt,
                evidence_quote, status, needs_human_review, confidence, category,
                justification, complexity, estimated_hours, delay_days,
                calculated_cost, recommended_charge, approval_status, decision_note, decided_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                a3, p3,
                "Campo de observações adicionais no pedido B2B",
                "Carrinho B2B e exportação CSV",
                "Escopo: Carrinho de pedidos B2B com envio ao painel do vendedor.",
                "incluir um campo de observação no pedido antes de exportar para CSV",
                "ALTERACAO_DE_ESCOPO", 0, 88, "Funcionalidade",
                "Pequena melhoria de formulário não listada originalmente, baixo esforço técnico.",
                "BAIXA", 3.0, 0, 300.00, 345.00, "APROVADA", "Absorvido na sprint atual para manter bom relacionamento.", "09/11/2026 09:00", "08/11/2026 16:00",
            ),
        )

        # Histórico de decisões inicial
        cur.executemany(
            """
            INSERT INTO decision_logs (item_id, project_name, requirement, action, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (3, "Desenvolvimento de Plataforma Digital", "Exportação de Relatórios Executivos em PDF com Gráficos", "EM_REVISAO", "Enviado para revisão comercial antes da proposta de aditivo.", "13/11/2026 10:15"),
                (4, "Desenvolvimento de Plataforma Digital", "Ajuste de cor do cabeçalho conforme manual de marca", "APROVADA", "Coberto pelo contrato, liberado para o time.", "12/11/2026 17:00"),
                (7, "Portal B2B Distribuidora Nordeste", "Campo de observações adicionais no pedido B2B", "APROVADA", "Absorvido na sprint atual sem cobrança extra.", "09/11/2026 09:00"),
                (6, "Plataforma FisioCare Gestão", "Emissão de Nota Fiscal Eletrônica (NF-e)", "RECUSADA", "Adiado para a Fase 2 após apresentação do impacto financeiro.", "06/11/2026 16:40"),
            ],
        )

    conn.commit()
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Scopeo — Inteligência de Gestão de Escopo", lifespan=lifespan)
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# --- Schemas Pydantic ---
class DecisionUpdate(BaseModel):
    approval_status: Literal["AGUARDANDO", "APROVADA", "RECUSADA", "EM_REVISAO"]
    note: str = ""


class AIExtractedItem(BaseModel):
    requirement: str = Field(description="Nome claro e executivo da solicitação feita pelo cliente.")
    contracted_item: str = Field(description="Funcionalidade ou item originalmente contratado relacionado.")
    contract_excerpt: str = Field(description="Trecho resumido ou cláusula do contrato que fundamenta a análise.")
    evidence_quote: str = Field(description="Trecho literal da transcrição/ata onde o cliente solicitou isso.")
    status: Literal["DENTRO_DO_ESCOPO", "ALTERACAO_DE_ESCOPO", "FORA_DO_ESCOPO"]
    needs_human_review: bool = Field(description="True se houver ambiguidade ou confiança menor que 85%.")
    confidence: int = Field(description="Grau de confiança da IA de 60 a 99.")
    category: Literal["Integração", "Funcionalidade", "Interface/UX", "Relatórios", "Segurança", "Financeiro", "Infraestrutura"]
    justification: str = Field(description="Justificativa objetiva comparando o pedido ao contrato.")
    complexity: Literal["BAIXA", "MEDIA", "ALTA"]
    estimated_hours: float = Field(description="Horas técnicas estimadas. Use 0 se for DENTRO_DO_ESCOPO.")
    delay_days: int = Field(description="Dias úteis extras no cronograma. Use 0 se for DENTRO_DO_ESCOPO.")


class AIAuditSchema(BaseModel):
    summary: str = Field(description="Resumo executivo de 2 frases sobre a auditoria.")
    items: List[AIExtractedItem]
    addendum_proposal: str = Field(
        description="Minuta de aditivo comercial cordial, firme e profissional em português com valores calculados."
    )


def compute_project_metrics(project: dict, items: List[dict]) -> dict:
    total_requests = len(items)
    out_items = [i for i in items if i["status"] == "FORA_DO_ESCOPO"]
    alt_items = [i for i in items if i["status"] == "ALTERACAO_DE_ESCOPO"]
    deviating = [i for i in items if i["status"] != "DENTRO_DO_ESCOPO"]
    pending = [i for i in items if i["approval_status"] in ("AGUARDANDO", "EM_REVISAO")]
    unformalized = [i for i in deviating if i["approval_status"] != "RECUSADA"]

    extra_hours = sum(float(i["estimated_hours"]) for i in unformalized)
    extra_cost = sum(float(i["calculated_cost"]) for i in unformalized)
    recommended_charge = sum(float(i["recommended_charge"]) for i in unformalized)
    delay_days = sum(int(i["delay_days"]) for i in unformalized)

    contract_val = max(float(project["contract_value"]), 1.0)
    est_hours = max(float(project["estimated_hours"]), 1.0)

    out_pct = round((len(out_items) / total_requests) * 100, 1) if total_requests else 0.0
    fin_pct = round((extra_cost / contract_val) * 100, 1)
    hours_pct = round((extra_hours / est_hours) * 100, 1)
    unformalized_count = len([i for i in deviating if i["approval_status"] in ("AGUARDANDO", "EM_REVISAO")])

    # Prévia configurável do Scope Deviation Index (0 a 100)
    raw_sdi = min(100, round(fin_pct * 2.2 + hours_pct * 1.4 + out_pct * 0.25 + unformalized_count * 5))
    if raw_sdi >= 60:
        risk_level = "ALTO"
    elif raw_sdi >= 25:
        risk_level = "MODERADO"
    else:
        risk_level = "BAIXO"

    alerts = []
    if fin_pct >= 15:
        alerts.append({
            "type": "danger",
            "title": "Risco de estouro orçamentário",
            "description": f"Solicitações acumuladas elevam o custo em {fin_pct}% (R$ {extra_cost:,.2f}) sobre o contrato original.",
        })
    if delay_days >= 3:
        alerts.append({
            "type": "warning",
            "title": "Possibilidade de atraso na entrega",
            "description": f"As mudanças identificadas podem adicionar cerca de {delay_days} dias úteis ao cronograma de {project['deadline_days']} dias.",
        })
    if unformalized_count > 0:
        alerts.append({
            "type": "warning",
            "title": "Mudanças ainda não formalizadas contratualmente",
            "description": f"Existem {unformalized_count} solicitações fora ou alterando o escopo aguardando formalização de aditivo.",
        })
    if len(out_items) >= 2:
        alerts.append({
            "type": "info",
            "title": "Aumento na frequência de solicitações",
            "description": f"Foram detectadas {len(out_items)} demandas diretamente conflitantes com cláusulas de exclusão.",
        })
    if not alerts:
        alerts.append({
            "type": "success",
            "title": "Escopo sob controle",
            "description": "Nenhum desvio crítico detectado nas reuniões auditadas até o momento.",
        })

    return {
        "total_requests": total_requests,
        "out_of_scope_count": len(out_items),
        "altered_count": len(alt_items),
        "pending_count": len(pending),
        "unformalized_count": unformalized_count,
        "extra_hours": round(extra_hours, 1),
        "extra_cost": round(extra_cost, 2),
        "new_estimated_cost": round(contract_val + extra_cost, 2),
        "recommended_charge": round(recommended_charge, 2),
        "budget_increase_pct": fin_pct,
        "hours_increase_pct": hours_pct,
        "out_of_scope_pct": out_pct,
        "delay_days": delay_days,
        "sdi": raw_sdi,
        "risk_level": risk_level,
        "alerts": alerts,
    }


def fallback_contract_analysis(project: sqlite3.Row, title: str, transcript: str) -> AIAuditSchema:
    stopwords = {"para", "com", "uma", "que", "dos", "das", "pelo", "pela", "sobre", "como", "mais", "tambem", "apenas", "sistema", "painel", "nosso", "nossa"}

    def kw(text: str) -> set:
        return {w for w in re.findall(r"[a-zA-ZÀ-ÿ0-9]{4,}", text.lower()) if w not in stopwords}

    excluded_lines = [l.strip("-• ").strip() for l in project["scope_excluded"].splitlines() if l.strip()]
    included_lines = [l.strip("-• ").strip() for l in project["scope_included"].splitlines() if l.strip()]
    clauses = [c.strip() for c in re.split(r"[.!?\n]+|,\s*(?=e também|mas|além disso|ah,)", transcript) if len(c.strip()) > 12]

    items: List[AIExtractedItem] = []
    for clause in clauses:
        c_words = kw(clause)
        if not c_words:
            continue

        matched_ex = next((ex for ex in excluded_lines if len(c_words.intersection(kw(ex))) >= 1), None)
        if matched_ex:
            low = clause.lower()
            cat = "Integração" if any(k in low for k in ["erp", "sap", "api", "whatsapp", "correios", "integr"]) else ("Segurança" if any(k in low for k in ["login", "sso", "google", "oauth"]) else "Funcionalidade")
            items.append(
                AIExtractedItem(
                    requirement=clause[:70].rstrip(".,"),
                    contracted_item="Escopo base contratado",
                    contract_excerpt=f"Cláusula de exclusão: {matched_ex}",
                    evidence_quote=clause,
                    status="FORA_DO_ESCOPO",
                    needs_human_review=False,
                    confidence=93,
                    category=cat,
                    justification=f"Conflita diretamente com item excluído no contrato: '{matched_ex}'.",
                    complexity="ALTA",
                    estimated_hours=14.0,
                    delay_days=2,
                )
            )
            continue

        matched_inc = next((inc for inc in included_lines if len(c_words.intersection(kw(inc))) >= 1), None)
        if matched_inc:
            items.append(
                AIExtractedItem(
                    requirement=clause[:70].rstrip(".,"),
                    contracted_item=matched_inc[:65],
                    contract_excerpt=f"Previsto em contrato: {matched_inc}",
                    evidence_quote=clause,
                    status="DENTRO_DO_ESCOPO",
                    needs_human_review=False,
                    confidence=90,
                    category="Interface/UX" if "cor" in clause.lower() or "botão" in clause.lower() else "Funcionalidade",
                    justification=f"Aderente ao item já contratado: '{matched_inc}'.",
                    complexity="BAIXA",
                    estimated_hours=0.0,
                    delay_days=0,
                )
            )
        elif any(v in clause.lower() for v in ["precisamos", "queria", "coloque", "integr", "api", "pdf", "relatório", "automático", "novo", "exportar", "frete", "mobile"]):
            items.append(
                AIExtractedItem(
                    requirement=clause[:70].rstrip(".,"),
                    contracted_item="Funcionalidade correlata no contrato",
                    contract_excerpt="Escopo original não detalha esta especificação adicional.",
                    evidence_quote=clause,
                    status="ALTERACAO_DE_ESCOPO",
                    needs_human_review=True,
                    confidence=76,
                    category="Relatórios" if "pdf" in clause.lower() or "relatório" in clause.lower() else "Funcionalidade",
                    justification="Solicitação representa expansão ou modificação de item existente; recomendada revisão humana.",
                    complexity="MEDIA",
                    estimated_hours=8.0,
                    delay_days=1,
                )
            )

    if not items:
        items.append(
            AIExtractedItem(
                requirement="Demanda identificada em ata para revisão",
                contracted_item="Escopo geral do projeto",
                contract_excerpt="Comparação com escopo geral contratado.",
                evidence_quote=transcript[:160],
                status="ALTERACAO_DE_ESCOPO",
                needs_human_review=True,
                confidence=72,
                category="Funcionalidade",
                justification="Item extraído da comunicação que exige validação contra o contrato original.",
                complexity="MEDIA",
                estimated_hours=6.0,
                delay_days=1,
            )
        )

    dev_items = [i for i in items if i.status != "DENTRO_DO_ESCOPO"]
    total_h = sum(i.estimated_hours for i in dev_items)
    total_cost = total_h * float(project["hourly_rate"])

    if dev_items:
        proposal = (
            f"Olá equipe {project['client_name']}! Consolidamos os pontos da auditoria '{title}'. "
            f"Identificamos {len(dev_items)} solicitação(ões) além do escopo contratado, totalizando {total_h:.0f}h técnicas adicionais "
            f"e impacto estimado de R$ {total_cost:,.2f} (valor recomendado de aditivo: R$ {total_cost * 1.15:,.2f}). "
            f"Podemos formalizar o termo aditivo antes de iniciar o desenvolvimento?"
        )
    else:
        proposal = f"Olá equipe {project['client_name']}! Todos os pontos alinhados em '{title}' estão cobertos pelo contrato original, sem custo adicional."

    return AIAuditSchema(
        summary=f"Auditoria concluída para '{title}': identificadas {len(items)} solicitações, sendo {len(dev_items)} com impacto sobre o escopo original.",
        items=items,
        addendum_proposal=proposal,
    )


def call_gemini_with_resilience(api_key: str, prompt: str) -> AIAuditSchema:
    client = genai.Client(api_key=api_key)
    candidate_models = [
        "gemini-3.8-flash",
        "gemini-3.8-flash-lite",
        "gemini-3.8-pro",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
    ]
    try:
        for m in client.models.list():
            clean = getattr(m, "name", "").replace("models/", "")
            low = clean.lower()
            if "gemini" in low and not any(x in low for x in ["embedding", "imagen", "veo", "tts", "audio", "robotics", "aqa"]):
                if clean not in candidate_models:
                    candidate_models.append(clean)
    except Exception:
        pass

    last_err = None
    for model_name in candidate_models[:6]:
        try:
            print(f"[Scopeo AI] Auditando com modelo: {model_name}...")
            res = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=AIAuditSchema,
                    temperature=0.2,
                ),
            )
            print(f"[Scopeo AI] Concluído com {model_name}!")
            return AIAuditSchema.model_validate_json(res.text)
        except Exception as err:
            last_err = err
            if any(c in str(err) for c in ["503", "404", "429", "UNAVAILABLE", "NOT_FOUND", "RESOURCE_EXHAUSTED"]):
                time.sleep(0.8)
                continue
            raise err
    raise last_err


# --- ROTAS ---
@app.get("/")
def serve_home():
    return FileResponse("static/index.html")


@app.get("/api/overview")
def get_overview():
    conn = get_db()
    projects_rows = conn.execute("SELECT * FROM projects ORDER BY id ASC").fetchall()
    all_items = [dict(r) for r in conn.execute("SELECT * FROM audit_items ORDER BY id DESC").fetchall()]
    all_audits = [dict(r) for r in conn.execute(
        "SELECT a.*, p.name as project_name, p.client_name FROM audits a JOIN projects p ON p.id = a.project_id ORDER BY a.id DESC LIMIT 10"
    ).fetchall()]
    conn.close()

    enriched_projects = []
    for pr in projects_rows:
        p = dict(pr)
        p_items = [i for i in all_items if i["project_id"] == p["id"]]
        p["metrics"] = compute_project_metrics(p, p_items)
        enriched_projects.append(p)

    risk_projects = [p for p in enriched_projects if p["metrics"]["risk_level"] in ("MODERADO", "ALTO")]
    ai_additional = [i for i in all_items if i["status"] != "DENTRO_DO_ESCOPO"]
    pending_approval = [i for i in all_items if i["approval_status"] in ("AGUARDANDO", "EM_REVISAO")]
    total_extra_cost = sum(p["metrics"]["extra_cost"] for p in enriched_projects)

    # Série mensal coerente combinando histórico base + impacto atual
    monthly_series = {
        "labels": ["Jul", "Ago", "Set", "Out", "Nov"],
        "values": [
            1200.0,
            2150.0,
            3400.0,
            round(total_extra_cost * 0.62, 2),
            round(total_extra_cost, 2),
        ],
    }

    activities = []
    for a in all_audits[:5]:
        activities.append({
            "type": "audit",
            "title": f"Auditoria concluída: {a['meeting_title']}",
            "subtitle": f"{a['project_name']} • Impacto de R$ {a['extra_cost']:,.2f}",
            "date": a["created_at"],
        })
    for it in ai_additional[:4]:
        p_name = next((p["name"] for p in enriched_projects if p["id"] == it["project_id"]), "Projeto")
        activities.append({
            "type": "request",
            "title": f"IA detectou: {it['requirement']}",
            "subtitle": f"{p_name} • {it['status'].replace('_', ' ')}",
            "date": it["created_at"],
        })

    return {
        "kpis": {
            "active_projects": len(enriched_projects),
            "projects_at_risk": len(risk_projects),
            "ai_requests_count": len(ai_additional),
            "accumulated_impact": round(total_extra_cost, 2),
            "pending_approvals": len(pending_approval),
        },
        "monthly_evolution": monthly_series,
        "projects": enriched_projects,
        "activities": activities[:8],
    }


@app.get("/api/projects")
def list_projects():
    return get_overview()["projects"]


@app.post("/api/projects")
async def create_project(
    name: str = Form(...),
    client_name: str = Form(...),
    start_date: str = Form(...),
    due_date: str = Form(...),
    contract_value: float = Form(...),
    hourly_rate: float = Form(110.0),
    scope_included: str = Form(""),
    scope_excluded: str = Form(""),
    contract_file: Optional[UploadFile] = File(None),
):
    contract_filename = ""
    extracted_contract = ""
    if contract_file and contract_file.filename:
        contract_filename = contract_file.filename
        raw = await contract_file.read()
        extracted_contract = extract_file_text(contract_filename, raw)

    # Calcula prazo em dias entre datas ou usa 45 dias padrão
    deadline_days = 45
    try:
        d1 = datetime.strptime(start_date, "%Y-%m-%d")
        d2 = datetime.strptime(due_date, "%Y-%m-%d")
        deadline_days = max(1, (d2 - d1).days)
        start_fmt = d1.strftime("%d/%m/%Y")
        due_fmt = d2.strftime("%d/%m/%Y")
    except Exception:
        start_fmt = start_date
        due_fmt = due_date

    est_hours = round(contract_value / max(hourly_rate, 1.0), 1)
    inc_text = scope_included.strip() or (
        extracted_contract[:900] if extracted_contract else "- Entregas principais definidas no contrato original.\n- Painel web e autenticação padrão."
    )
    exc_text = scope_excluded.strip() or "- Integrações com ERPs externos não listados.\n- Aplicativos móveis nativos e módulos fiscais."

    conn = get_db()
    cur = conn.cursor()
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    cur.execute(
        """
        INSERT INTO projects (
            name, client_name, start_date, due_date, deadline_days,
            contract_value, estimated_hours, hourly_rate, status,
            scope_objectives, scope_deliverables, scope_included,
            scope_excluded, payment_terms, contract_filename, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            client_name,
            start_fmt,
            due_fmt,
            deadline_days,
            contract_value,
            est_hours,
            hourly_rate,
            "Em andamento",
            f"Entregar o projeto {name} para {client_name} dentro do orçamento de R$ {contract_value:,.2f} e prazo de {deadline_days} dias.",
            "- Escopo técnico homologado conforme contrato anexado\n- Entrega em ambiente de produção e documentação",
            inc_text,
            exc_text,
            f"Valor fechado de R$ {contract_value:,.2f}. Horas técnicas adicionais precificadas em R$ {hourly_rate:,.2f}/h.",
            contract_filename or "Contrato_Original.pdf",
            now,
        ),
    )
    project_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"id": project_id, "message": "Projeto cadastrado com sucesso"}


@app.get("/api/projects/{project_id}")
def get_project_details(project_id: int):
    conn = get_db()
    project_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    project = dict(project_row)
    audits_rows = conn.execute("SELECT * FROM audits WHERE project_id = ? ORDER BY id DESC", (project_id,)).fetchall()
    items_rows = conn.execute(
        """
        SELECT i.*, a.meeting_title, a.source_type, a.created_at as audit_date
        FROM audit_items i
        JOIN audits a ON a.id = i.audit_id
        WHERE i.project_id = ?
        ORDER BY i.id DESC
        """,
        (project_id,),
    ).fetchall()
    conn.close()

    items = [dict(i) for i in items_rows]
    audits = []
    for a in audits_rows:
        ad = dict(a)
        ad["items"] = [i for i in items if i["audit_id"] == ad["id"]]
        audits.append(ad)

    metrics = compute_project_metrics(project, items)
    return {"project": project, "metrics": metrics, "audits": audits, "items": items}


@app.post("/api/projects/{project_id}/audit")
async def run_scope_audit(
    project_id: int,
    meeting_title: str = Form(...),
    source_type: str = Form("Transcrição"),
    transcript: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    filename = ""
    final_transcript = transcript.strip()
    if file and file.filename:
        filename = file.filename
        raw = await file.read()
        extracted = extract_file_text(filename, raw).strip()
        final_transcript = f"{final_transcript}\n\n{extracted}".strip() if final_transcript else extracted

    if not final_transcript:
        raise HTTPException(status_code=400, detail="Envie um arquivo (PDF/TXT) ou cole o texto da ata/transcrição.")

    conn = get_db()
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        conn.close()
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    prompt = f"""
Você é o motor de inteligência contratual da plataforma Scopeo.
Analise a comunicação abaixo comparando rigorosamente com o contrato original do projeto.

PROJETO: {project['name']} (Cliente: {project['client_name']})
VALOR/HORA CONTRATUAL: R$ {project['hourly_rate']:.2f}

=== ESCOPO INCLUÍDO ===
{project['scope_included']}

=== EXPLICITAMENTE EXCLUÍDO ===
{project['scope_excluded']}

=== DOCUMENTO AUDITADO ({source_type}): {meeting_title} ===
{final_transcript}

Regras:
1. Extraia cada solicitação/mudança mencionada pelo cliente.
2. Classifique em DENTRO_DO_ESCOPO, ALTERACAO_DE_ESCOPO ou FORA_DO_ESCOPO.
3. Marque needs_human_review=true se houver ambiguidade contratual ou confiança < 85.
4. Para DENTRO_DO_ESCOPO use estimated_hours=0 e delay_days=0.
5. Gere uma minuta de aditivo comercial clara e profissional com base em R$ {project['hourly_rate']:.2f}/h.
"""

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    ai_engine_used = "Gemini Structured AI"
    if api_key and api_key != "COLE_SUA_CHAVE_AQUI":
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(call_gemini_with_resilience, api_key, prompt)
                ai_result = future.result(timeout=28)
        except Exception as e:
            print(f"[Scopeo AI] Fallback local ativado: {e}")
            ai_result = fallback_contract_analysis(project, meeting_title, final_transcript)
            ai_engine_used = "Motor Heurístico de Contingência"
    else:
        ai_result = fallback_contract_analysis(project, meeting_title, final_transcript)
        ai_engine_used = "Motor Heurístico Local"

    hourly_rate = float(project["hourly_rate"])
    total_extra_hours = 0.0
    total_extra_cost = 0.0
    processed = []

    for item in ai_result.items:
        hours = item.estimated_hours if item.status != "DENTRO_DO_ESCOPO" else 0.0
        delay = item.delay_days if item.status != "DENTRO_DO_ESCOPO" else 0
        cost = round(hours * hourly_rate, 2)
        rec_charge = round(cost * 1.15, 2) if cost > 0 else 0.0
        if item.status != "DENTRO_DO_ESCOPO":
            total_extra_hours += hours
            total_extra_cost += cost
        processed.append((item, hours, delay, cost, rec_charge))

    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO audits (
            project_id, meeting_title, source_type, filename, transcript,
            summary, addendum_proposal, extra_hours, extra_cost, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id, meeting_title, source_type, filename, final_transcript,
            ai_result.summary, ai_result.addendum_proposal, total_extra_hours, total_extra_cost, now,
        ),
    )
    audit_id = cur.lastrowid

    for item, hours, delay, cost, rec_charge in processed:
        initial_approval = "APROVADA" if item.status == "DENTRO_DO_ESCOPO" else ("EM_REVISAO" if item.needs_human_review else "AGUARDANDO")
        cur.execute(
            """
            INSERT INTO audit_items (
                audit_id, project_id, requirement, contracted_item, contract_excerpt,
                evidence_quote, status, needs_human_review, confidence, category,
                justification, complexity, estimated_hours, delay_days,
                calculated_cost, recommended_charge, approval_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id, project_id, item.requirement, item.contracted_item, item.contract_excerpt,
                item.evidence_quote, item.status, 1 if item.needs_human_review else 0, item.confidence,
                item.category, item.justification, item.complexity, hours, delay,
                cost, rec_charge, initial_approval, now,
            ),
        )

    conn.commit()
    conn.close()
    return {"audit_id": audit_id, "engine": ai_engine_used, "message": "Auditoria concluída com sucesso"}


@app.get("/api/requests")
def list_all_requests(project_id: Optional[int] = None):
    conn = get_db()
    query = """
        SELECT i.*, p.name as project_name, p.client_name, p.hourly_rate,
               a.meeting_title, a.source_type, a.filename
        FROM audit_items i
        JOIN projects p ON p.id = i.project_id
        JOIN audits a ON a.id = i.audit_id
    """
    params = []
    if project_id:
        query += " WHERE i.project_id = ?"
        params.append(project_id)
    query += " ORDER BY i.id DESC"
    rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()
    return rows


@app.get("/api/audits")
def list_all_audits(project_id: Optional[int] = None):
    conn = get_db()
    query = """
        SELECT a.*, p.name as project_name, p.client_name,
               (SELECT COUNT(*) FROM audit_items i WHERE i.audit_id = a.id) as items_count
        FROM audits a
        JOIN projects p ON p.id = a.project_id
    """
    params = []
    if project_id:
        query += " WHERE a.project_id = ?"
        params.append(project_id)
    query += " ORDER BY a.id DESC"
    rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()
    return rows


@app.patch("/api/requests/{item_id}/decision")
def update_request_decision(item_id: int, payload: DecisionUpdate):
    conn = get_db()
    item = conn.execute(
        "SELECT i.*, p.name as project_name FROM audit_items i JOIN projects p ON p.id = i.project_id WHERE i.id = ?",
        (item_id,),
    ).fetchone()
    if not item:
        conn.close()
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")

    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    cur = conn.cursor()
    cur.execute(
        "UPDATE audit_items SET approval_status = ?, decision_note = ?, decided_at = ? WHERE id = ?",
        (payload.approval_status, payload.note, now, item_id),
    )
    cur.execute(
        "INSERT INTO decision_logs (item_id, project_name, requirement, action, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, item["project_name"], item["requirement"], payload.approval_status, payload.note, now),
    )
    conn.commit()
    conn.close()
    return {"message": "Decisão registrada com sucesso"}


@app.get("/api/approvals")
def get_approvals_data(project_id: Optional[int] = None):
    items = list_all_requests(project_id)
    conn = get_db()
    logs = [dict(r) for r in conn.execute("SELECT * FROM decision_logs ORDER BY id DESC LIMIT 20").fetchall()]
    conn.close()
    return {"items": items, "logs": logs}


@app.get("/api/financial")
def get_financial_data(project_id: Optional[int] = None):
    overview = get_overview()
    projects = overview["projects"]
    if project_id:
        projects = [p for p in projects if p["id"] == project_id]

    items = [i for i in list_all_requests(project_id) if i["status"] != "DENTRO_DO_ESCOPO" and i["approval_status"] != "RECUSADA"]

    orig_budget = sum(float(p["contract_value"]) for p in projects)
    extra_cost = sum(float(i["calculated_cost"]) for i in items)
    extra_hours = sum(float(i["estimated_hours"]) for i in items)
    recommended = sum(float(i["recommended_charge"]) for i in items)
    pct_inc = round((extra_cost / orig_budget) * 100, 1) if orig_budget > 0 else 0.0

    cat_map = {}
    for i in items:
        cat_map[i["category"]] = cat_map.get(i["category"], 0.0) + float(i["calculated_cost"])

    return {
        "kpis": {
            "original_budget": round(orig_budget, 2),
            "additional_cost": round(extra_cost, 2),
            "new_estimated_budget": round(orig_budget + extra_cost, 2),
            "increase_pct": pct_inc,
            "extra_hours": round(extra_hours, 1),
            "recommended_charge": round(recommended, 2),
        },
        "evolution": {
            "labels": ["Jul", "Ago", "Set", "Out", "Nov"],
            "values": [950.0, 1800.0, 2900.0, round(extra_cost * 0.65, 2), round(extra_cost, 2)],
        },
        "by_request": [{"label": i["requirement"][:28], "value": i["calculated_cost"]} for i in items[:7]],
        "by_category": [{"label": k, "value": round(v, 2)} for k, v in cat_map.items()],
        "table": items,
    }


@app.get("/api/insights")
def get_ai_insights():
    overview = get_overview()
    projects = overview["projects"]
    items = list_all_requests()

    insights = []
    # 1. Projeto com maior risco financeiro
    sorted_proj = sorted(projects, key=lambda p: p["metrics"]["extra_cost"], reverse=True)
    if sorted_proj and sorted_proj[0]["metrics"]["extra_cost"] > 0:
        top = sorted_proj[0]
        insights.append({
            "priority": "Alta",
            "category": "Risco Financeiro",
            "icon": "trending-up",
            "title": f"Risco de estouro orçamentário em {top['name']}",
            "description": f"Foram identificadas {top['metrics']['out_of_scope_count'] + top['metrics']['altered_count']} solicitações fora/alterando o escopo ({top['client_name']}), representando R$ {top['metrics']['extra_cost']:,.2f} (+{top['metrics']['budget_increase_pct']}%) em custos adicionais estimados.",
            "recommendation": "Formalizar imediatamente um termo aditivo contemplando as horas técnicas extras antes de iniciar o próximo sprint.",
        })

    # 2. Atraso acumulado no cronograma
    total_delay = sum(p["metrics"]["delay_days"] for p in projects)
    if total_delay > 0:
        insights.append({
            "priority": "Alta",
            "category": "Cronograma",
            "icon": "clock",
            "title": "Possível atraso consolidado nas entregas",
            "description": f"As alterações não previstas identificadas pela IA podem adicionar até {total_delay} dias úteis ao cronograma original da carteira de projetos.",
            "recommendation": "Renegociar as datas de entrega proporcionais ao esforço extra no mesmo documento de aditivo financeiro.",
        })

    # 3. Categoria mais recorrente
    cat_counts = {}
    for i in items:
        if i["status"] != "DENTRO_DO_ESCOPO":
            cat_counts[i["category"]] = cat_counts.get(i["category"], 0) + 1
    if cat_counts:
        top_cat = max(cat_counts, key=cat_counts.get)
        insights.append({
            "priority": "Média",
            "category": "Padrão de Escopo",
            "icon": "layers",
            "title": f"Categoria mais recorrente de desvios: {top_cat}",
            "description": f"Demandas de '{top_cat}' representam o maior volume de solicitações fora do contrato ({cat_counts[top_cat]} ocorrências detectadas nas atas).",
            "recommendation": f"Reforçar o checklist pré-venda e criar cláusulas mais explícitas para '{top_cat}' nas próximas propostas comerciais.",
        })

    # 4. Pendências sem formalização
    pending = [i for i in items if i["approval_status"] in ("AGUARDANDO", "EM_REVISAO")]
    if pending:
        pending_val = sum(float(i["recommended_charge"]) for i in pending)
        insights.append({
            "priority": "Alta",
            "category": "Governança",
            "icon": "file-warning",
            "title": f"{len(pending)} mudanças aguardando decisão formal",
            "description": f"Há R$ {pending_val:,.2f} em valor comercial recomendável ainda sem aprovação ou recusa formal na fila de Aprovações.",
            "recommendation": "Utilize a tela de Aprovações para gerar os relatórios de alteração e alinhar formalmente com os clientes.",
        })

    # 5. Contradição contratual recorrente
    direct_conflicts = [i for i in items if i["status"] == "FORA_DO_ESCOPO"]
    if direct_conflicts:
        insights.append({
            "priority": "Média",
            "category": "Contradição Contratual",
            "icon": "shield-alert",
            "title": "Solicitações em conflito direto com cláusulas de exclusão",
            "description": f"A IA mapeou {len(direct_conflicts)} pedidos em reuniões que contrariam itens expressamente excluídos nos contratos assinados.",
            "recommendation": "Apresentar a Matriz 'Contratado vs. Solicitado' na próxima reunião de checkpoint para embasar a conversa com evidências objetivas.",
        })

    return insights