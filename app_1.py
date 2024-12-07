import streamlit as st
import anthropic
import pandas as pd
import PyPDF2
import io
import re
import uuid
import time
import traceback
from typing import Dict, List, Tuple

class ChatMessage:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content

def chunk_pages_into_files(pages_content: Dict[int, str], pages_per_chunk: int = 25) -> List[Dict[int, str]]:
    """Divide el contenido en chunks más pequeños"""
    st.write("Iniciando chunk_pages_into_files")  # Debug
    pages_list = sorted(pages_content.items())
    st.write(f"Total páginas a procesar: {len(pages_list)}")  # Debug
    chunks = []
    
    for i in range(0, len(pages_list), pages_per_chunk):
        chunk = dict(pages_list[i:i + pages_per_chunk])
        chunks.append(chunk)
    
    st.write(f"Chunks creados: {len(chunks)}")  # Debug
    return chunks

def parse_text_with_pages(text):
    st.write("Iniciando parse_text_with_pages")  # Debug
    pages = {}
    current_page = None
    current_content = []
    current_header = ""
    
    lines = text.split('\n')
    st.write(f"Líneas a procesar: {len(lines)}")  # Debug
    
    try:
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
                st.write(f"Encontrada página {current_page}")  # Debug
        
        if current_page and current_content:
            pages[current_page] = current_header + '\n'.join(current_content)
        
        st.write(f"Páginas encontradas: {len(pages)}")  # Debug
        st.write(f"Números de página: {sorted(pages.keys())}")  # Debug
        return pages
    except Exception as e:
        st.error(f"Error en parse_text_with_pages: {str(e)}")
        st.write(f"Traza del error: {traceback.format_exc()}")  # Debug
        raise e

def extract_text_from_file(uploaded_file):
    try:
        st.write(f"Procesando archivo tipo: {uploaded_file.type}")  # Debug
        if uploaded_file.type == "application/pdf":
            pdf_reader = PyPDF2.PdfReader(uploaded_file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text
        elif uploaded_file.type == "text/plain":
            text = uploaded_file.getvalue().decode("utf-8")
            st.write(f"Longitud del texto cargado: {len(text)}")  # Debug
            st.write("Primeras 100 caracteres:")  # Debug
            st.write(text[:100])  # Debug
            pages = parse_text_with_pages(text)
            return {"text": text, "pages": pages}
        else:
            return "Formato de archivo no soportado"
    except Exception as e:
        st.error(f"Error en extract_text_from_file: {str(e)}")
        st.write(f"Traza del error: {traceback.format_exc()}")  # Debug
        raise e

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

def query_chunk(client, chunk: Dict[int, str], prompt: str, chunk_info: str) -> str:
    """Consulta un chunk específico"""
    formatted_messages = []
    content_message = f"""Analizando {chunk_info}:
    
    """
    for page, content in sorted(chunk.items()):
        content_message += f"{content}\n\n"
    
    formatted_messages.append({
        "role": "user",
        "content": content_message
    })
    formatted_messages.append({"role": "user", "content": prompt})
    
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=4096,
        messages=formatted_messages,
        system="""Eres un asistente especializado en análisis de documentos. REGLAS:
1. Los ejercicios pertenecen a la página indicada en la etiqueta [Pagina X] que los precede
2. Busca en TODAS las páginas proporcionadas
3. Especifica el número exacto de página para cada ejercicio
4. Mantén respuestas concisas pero completas"""
    )
    
    return response.content[0].text

def main():
    st.set_page_config(
        page_title="Chat con Claude",
        page_icon="🤖",
        layout="wide"
    )

    if "file_chunks" not in st.session_state:
        st.session_state.file_chunks = []
    if "current_chunk" not in st.session_state:
        st.session_state.current_chunk = 0
    if "combined_response" not in st.session_state:
        st.session_state.combined_response = ""

    st.sidebar.title("⚙️ Configuración")
    api_key = st.sidebar.text_input("API Key de Anthropic", type="password")

    st.sidebar.markdown("### 📄 Cargar Archivo")
    uploaded_file = st.sidebar.file_uploader("Sube un archivo PDF o TXT", type=['pdf', 'txt'])

    st.sidebar.markdown("### 🗑️ Gestión del Chat")
    if st.sidebar.button("Limpiar Conversación", type="primary", use_container_width=True):
        st.session_state.messages = []
        st.session_state.file_chunks = []
        st.session_state.current_chunk = 0
        st.session_state.combined_response = ""
        st.rerun()

    if "messages" not in st.session_state:
        st.session_state.messages = []

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
            st.write("Archivo detectado")  # Debug
            st.write(f"Tipo de archivo: {uploaded_file.type}")  # Debug
            st.write(f"Nombre de archivo: {uploaded_file.name}")  # Debug
            
            try:
                # Intentar leer el contenido del archivo
                content = uploaded_file.getvalue()
                st.write(f"Contenido leído: {len(content)} bytes")  # Debug
                
                if "last_file" not in st.session_state or st.session_state.last_file != uploaded_file.name:
                    with st.spinner("Procesando archivo..."):
                        try:
                            st.write("Iniciando procesamiento")  # Debug
                            file_content = extract_text_from_file(uploaded_file)
                            st.write("Contenido extraído")  # Debug
                            
                            if isinstance(file_content, dict):
                                st.write("Archivo procesado como diccionario")  # Debug
                                st.write(f"Número de páginas: {len(file_content['pages'])}")  # Debug
                                st.session_state.pages_content = file_content["pages"]
                                st.session_state.file_chunks = chunk_pages_into_files(file_content["pages"])
                                st.write(f"Chunks creados: {len(st.session_state.file_chunks)}")  # Debug
                            else:
                                st.write(f"Archivo no procesado correctamente: {file_content}")  # Debug
                                st.session_state.pages_content = None
                                st.session_state.file_chunks = []
                            
                            st.session_state.last_file = uploaded_file.name
                            
                        except Exception as e:
                            st.error(f"Error durante el procesamiento: {str(e)}")
                            st.write(f"Traza del error: {traceback.format_exc()}")  # Debug
                    
                    st.sidebar.success(f"Archivo cargado: {uploaded_file.name}")
            except Exception as e:
                st.error(f"Error al leer el archivo: {str(e)}")
                st.write(f"Traza del error: {traceback.format_exc()}")  # Debug

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
                    st.write(f"Estado de los chunks: {len(st.session_state.file_chunks)}")  # Debug
                    if st.session_state.file_chunks:
                        st.write("Iniciando procesamiento de chunks")  # Debug
                        combined_response = ""
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        for i, chunk in enumerate(st.session_state.file_chunks):
                            chunk_start = min(chunk.keys())
                            chunk_end = max(chunk.keys())
                            chunk_info = f"páginas {chunk_start} a {chunk_end}"
                            st.write(f"Procesando chunk {i}: {chunk_info}")  # Debug
                            
                            status_text.text(f"Analizando {chunk_info}...")
                            
                            if i > 0:
                                status_text.text(f"Esperando para procesar siguiente chunk...")
                                time.sleep(65)  # Espera poco más de un minuto
                            
                            response = query_chunk(client, chunk, prompt, chunk_info)
                            if response.strip():
                                combined_response += f"\n\nResultados de {chunk_info}:\n{response}"
                            
                            progress = (i + 1) / len(st.session_state.file_chunks)
                            progress_bar.progress(progress)
                        
                        status_text.text("Análisis completado!")
                        st.session_state.combined_response = combined_response
                        detect_and_convert_csv(combined_response)
                        st.session_state.messages.append(ChatMessage("assistant", combined_response))
                    else:
                        st.write("No hay chunks para procesar")  # Debug
                        simple_response = client.messages.create(
                            model="claude-3-5-sonnet-20241022",
                            max_tokens=4096,
                            messages=[{"role": "user", "content": prompt}]
                        )
                        st.write(simple_response.content[0].text)
                        st.session_state.messages.append(ChatMessage("assistant", simple_response.content[0].text))

                except Exception as e:
                    st.error(f"Error en la comunicación con Claude: {str(e)}")
                    st.write(f"Detalles del error: {traceback.format_exc()}")  # Debug

    except Exception as e:
        st.error(f"Error de inicialización: {str(e)}")
        st.write(f"Detalles del error de inicialización: {traceback.format_exc()}")  # Debug

if __name__ == "__main__":
    main()
