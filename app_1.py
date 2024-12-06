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

def chunk_content(text, max_chars=2000):
    return text[:max_chars]

def get_page_chunks(pages_content, start_page=1, chunk_size=20):
    pages_list = sorted(pages_content.items(), key=lambda x: x[0])
    total_pages = len(pages_list)
    chunks = []
    
    for i in range(0, total_pages, chunk_size):
        chunk = dict(pages_list[i:i + chunk_size])
        chunks.append(chunk)
    
    return chunks

def parse_text_with_pages(text):
    pages = {}
    current_page = None
    current_content = []
    current_header = ""
    
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if match := re.match(r'\[Pagina (\d+)\]', line, re.IGNORECASE):
            if current_page:
                pages[current_page] = current_header + '\n'.join(current_content)
            current_page = int(match.group(1))
            current_header = line + '\n'
            current_content = []
            next_page_index = next((j for j, l in enumerate(lines[i+1:], i+1) 
                                  if re.match(r'\[Pagina \d+\]', l, re.IGNORECASE)), len(lines))
            current_content = lines[i+1:next_page_index]
    
    if current_page and current_content:
        pages[current_page] = current_header + '\n'.join(current_content)
    
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
                        if hasattr(st.session_state, 'pages_content') and st.session_state.pages_content:
                            chunks = get_page_chunks(st.session_state.pages_content)
                            for chunk in chunks:
                                content_message = """INSTRUCCIONES PARA BÚSQUEDA DE EJERCICIOS:
Los ejercicios están organizados bajo etiquetas [Pagina X].
Cada ejercicio pertenece a la página indicada en la etiqueta anterior.

Contenido del documento:\n\n"""
                                for page, content in sorted(chunk.items()):
                                    page_chunk = chunk_content(content, max_chars=2000)
                                    content_message += f"\n{page_chunk}\n"
                                
                                formatted_messages.append({
                                    "role": "user",
                                    "content": content_message
                                })
                        else:
                            content_message = "Contenido del documento:\n\n"
                            content_message += chunk_content(st.session_state.file_content, max_chars=50000)
                            formatted_messages.append({
                                "role": "user",
                                "content": content_message
                            })

                    formatted_messages.append({"role": "user", "content": prompt})

                    with st.spinner('Analizando...'):
                        response = client.messages.create(
                            model="claude-3-5-sonnet-20241022",
                            max_tokens=4096,
                            messages=formatted_messages,
                            system="""Eres un asistente especializado en análisis exhaustivo de documentos. REGLAS FUNDAMENTALES:

1. Cuando te pregunten por ejercicios de una página específica:
   - SOLO debes listar los ejercicios que aparecen después de la etiqueta [Pagina X] solicitada
   - El contenido de esa página termina cuando encuentres la siguiente etiqueta [Pagina]
   - Si te preguntan por ejercicios específicos, debes indicar en qué página están

2. Para cualquier búsqueda de ejercicios:
   - Busca la etiqueta [Pagina X] correspondiente
   - Lista TODOS los ejercicios que encuentres en esa sección
   - Indica siempre el número de página donde se encuentran

3. Realiza búsquedas EXHAUSTIVAS y no omitas ningún resultado.
4. Confirma explícitamente cuando hayas completado la búsqueda.
5. IMPORTANTE: Busca en TODO el documento proporcionado."""
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
