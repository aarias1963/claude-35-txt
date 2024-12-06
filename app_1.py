import streamlit as st
import anthropic
import pandas as pd
import PyPDF2
import io
import re
import uuid

class ChatMessage:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content

def chunk_content(text, max_chars=3000):
    return text[:max_chars]

def parse_text_with_pages(text):
    pages = {}
    current_page = None
    current_content = []
    
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if match := re.match(r'\[Pagina (\d+)\]', line, re.IGNORECASE):
            if current_page:
                pages[current_page] = '\n'.join(current_content)
            current_page = int(match.group(1))
            current_content = []
            next_page_index = next((j for j, l in enumerate(lines[i+1:], i+1) 
                                  if re.match(r'\[Pagina \d+\]', l, re.IGNORECASE)), len(lines))
            current_content = lines[i+1:next_page_index]
    
    if current_page and current_content:
        pages[current_page] = '\n'.join(current_content)
    
    return pages

def extract_text_from_file(uploaded_file):
    try:
        if uploaded_file.type == "application/pdf":
            pdf_reader = PyPDF2.PdfReader(uploaded_file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text
        elif uploaded_file.type == "text/plain":
            text = uploaded_file.getvalue().decode("utf-8")
            pages = parse_text_with_pages(text)
            return {"text": text, "pages": pages}
        else:
            return "Formato de archivo no soportado"
    except Exception as e:
        return f"Error al procesar el archivo: {str(e)}"

def detect_and_convert_csv(text):
    lines = text.split('\n')
    csv_blocks = []
    current_block = []
    in_csv_block = False
    
    for line in lines:
        is_csv_line = (',' in line or '\t' in line) and len(line.strip()) > 0
        
        if is_csv_line:
            if not in_csv_block:
                in_csv_block = True
            current_block.append(line)
        else:
            if in_csv_block:
                if len(current_block) > 1:
                    csv_blocks.append(current_block)
                current_block = []
                in_csv_block = False
            st.write(line)
    
    if in_csv_block and len(current_block) > 1:
        csv_blocks.append(current_block)
    
    for i, block in enumerate(csv_blocks):
        try:
            block_id = str(uuid.uuid4())
            df = pd.read_csv(io.StringIO('\n'.join(block)))
            st.dataframe(df)
            
            col1, col2 = st.columns(2)
            csv_data = df.to_csv(index=False)
            with col1:
                st.download_button(
                    label="📥 Descargar CSV",
                    data=csv_data,
                    file_name=f"datos_{i}.csv",
                    mime="text/csv",
                    key=f"csv_{block_id}"
                )
            
            excel_data = io.BytesIO()
            df.to_excel(excel_data, index=False, engine='openpyxl')
            excel_data.seek(0)
            with col2:
                st.download_button(
                    label="📥 Descargar Excel",
                    data=excel_data,
                    file_name=f"datos_{i}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"excel_{block_id}"
                )
            
        except Exception as e:
            st.error(f"Error al procesar datos tabulares: {str(e)}")
            st.text('\n'.join(block))

def main():
    st.set_page_config(
        page_title="Chat con Claude",
        page_icon="🤖",
        layout="wide"
    )

    st.sidebar.title("⚙️ Configuración")
    api_key = st.sidebar.text_input("API Key de Anthropic", type="password")

    st.sidebar.markdown("### 📄 Cargar Archivo")
    uploaded_file = st.sidebar.file_uploader("Sube un archivo PDF o TXT", type=['pdf', 'txt'])

    st.sidebar.markdown("### 🗑️ Gestión del Chat")
    if st.sidebar.button("Limpiar Conversación", type="primary", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "file_content" not in st.session_state:
        st.session_state.file_content = ""

    st.title("💬 Chat con Claude 3.5 Sonnet")
    st.markdown("""
    Esta aplicación te permite chatear con Claude 3.5 Sonnet usando la API de Anthropic.
    Si cargas un PDF o TXT, Claude realizará búsquedas exhaustivas en su contenido.
    """)

    if not api_key:
        st.warning("👈 Introduce tu API Key en la barra lateral para comenzar.")
        return

    try:
        client = anthropic.Client(api_key=api_key)
        
        if uploaded_file:
            if "last_file" not in st.session_state or st.session_state.last_file != uploaded_file.name:
                with st.spinner("Procesando archivo..."):
                    file_content = extract_text_from_file(uploaded_file)
                    if isinstance(file_content, dict):
                        st.session_state.file_content = file_content["text"]
                        st.session_state.pages_content = file_content["pages"]
                    else:
                        st.session_state.file_content = file_content
                        st.session_state.pages_content = None
                    st.session_state.last_file = uploaded_file.name
                st.sidebar.success(f"Archivo cargado: {uploaded_file.name}")

        for message in st.session_state.messages:
            with st.chat_message(message.role):
                if message.role == "assistant":
                    detect_and_convert_csv(message.content)
                else:
                    st.write(message.content)

        if prompt := st.chat_input("Escribe tu mensaje aquí..."):
            st.session_state.messages.append(ChatMessage("user", prompt))
            with st.chat_message("user"):
                st.write(prompt)

            with st.chat_message("assistant"):
                try:
                    formatted_messages = []
                    
                    if st.session_state.file_content:
                        content_message = """Documento a analizar. El formato es el siguiente:
[Pagina X] seguido de los ejercicios que están en esa página.
Los ejercicios de cada página están entre su etiqueta [Pagina X] y la siguiente etiqueta [Pagina Y].
Cuando te pregunten por ejercicios, indica SIEMPRE su página basándote en este formato:\n\n"""
                        if hasattr(st.session_state, 'pages_content') and st.session_state.pages_content:
                            pages_list = sorted(st.session_state.pages_content.items(), key=lambda x: x[0])
                            for page, content in pages_list:
                                page_chunk = chunk_content(content, max_chars=3000)
                                content_message += f"[Pagina {page}]\n{page_chunk}\n\n"
                        else:
                            content_message += chunk_content(st.session_state.file_content, max_chars=50000)
                        
                        formatted_messages.append({
                            "role": "user",
                            "content": content_message
                        })

                    for msg in st.session_state.messages:
                        formatted_messages.append({"role": msg.role, "content": msg.content})

                    with st.spinner('Analizando...'):
                        response = client.messages.create(
                            model="claude-3-5-sonnet-20241022",
                            max_tokens=4096,
                            messages=formatted_messages,
                            system="""Eres un asistente especializado en análisis exhaustivo de documentos. Cuando se te pida buscar o analizar información:
                            1. Realiza una búsqueda EXHAUSTIVA y COMPLETA de TODAS las actividades, ejercicios o elementos que cumplan con los criterios especificados.
                            2. No omitas ningún resultado que cumpla con los criterios de búsqueda.
                            3. Organiza los resultados de forma clara, preferiblemente en formato tabular cuando sea apropiado.
                            4. Si encuentras múltiples elementos, debes listarlos TODOS, no solo algunos ejemplos.
                            5. Si la búsqueda inicial no es completa, realiza búsquedas adicionales hasta agotar todas las posibilidades.
                            6. Confirma explícitamente cuando hayas completado la búsqueda exhaustiva.
                            7. IMPORTANTE: Para identificar la página de un ejercicio, debes fijarte en la etiqueta [Pagina X] que lo precede. Todo el contenido que aparece después de una etiqueta [Pagina X] pertenece a esa página, hasta que encuentres la siguiente etiqueta [Pagina Y]."""
                        )

                        assistant_response = response.content[0].text
                        detect_and_convert_csv(assistant_response)
                        st.session_state.messages.append(ChatMessage("assistant", assistant_response))

                except Exception as e:
                    st.error(f"Error en la comunicación con Claude: {str(e)}")

    except Exception as e:
        st.error(f"Error de inicialización: {str(e)}")

if __name__ == "__main__":
    main()
