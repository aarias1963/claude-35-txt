import streamlit as st
import anthropic
import pandas as pd
import PyPDF2
import io
import re
import uuid
import time
import traceback
import csv
from typing import Dict, List, Tuple

class ChatMessage:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content

class Exercise:
    def __init__(self, number: str, page: int, description: str, standard: str):
        self.number = number
        self.page = page
        self.description = description
        self.standard = standard

def create_csv_from_exercises(exercises: List[Exercise]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Ejercicio', 'Página', 'Descripción', 'Estándar'])
    for exercise in exercises:
        writer.writerow([exercise.number, exercise.page, exercise.description, exercise.standard])
    return output.getvalue()

def parse_exercises_from_response(response: str) -> List[Exercise]:
    exercises = []
    # Patrón mejorado para capturar ejercicios incluso sin descripción
    exercise_pattern = r'Ejercicio\s+(\d+)\s*\(Página\s+(\d+)\)\s*:?\s*((?:(?!Ejercicio\s+\d+\s*\(Página).|[\n])*)'
    
    matches = re.finditer(exercise_pattern, response, re.DOTALL | re.IGNORECASE)
    
    for match in matches:
        number = match.group(1)
        page = int(match.group(2))
        description = match.group(3).strip() if match.group(3) else "Sin descripción"
        exercises.append(Exercise(number, page, description, ""))
            
    return exercises

def chunk_pages_into_files(pages_content: Dict[int, str], pages_per_chunk: int = 25) -> List[Dict[int, str]]:
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
    
    lines = text.split('\n')
    st.write(f"Líneas a procesar: {len(lines)}")  # Debug
    
    try:
        page_pattern = r'\[Página (\d+)\]'
        
        for i, line in enumerate(lines):
            match = re.match(page_pattern, line, re.UNICODE)
            if match:
                if current_page:
                    pages[current_page] = '\n'.join(current_content)
                current_page = int(match.group(1))
                current_content = []
                st.write(f"Procesando página {current_page}")  # Debug
            elif current_page is not None:
                current_content.append(line)
        
        if current_page and current_content:
            pages[current_page] = '\n'.join(current_content)
        
        st.write(f"Total páginas procesadas: {len(pages)}")  # Debug
        return pages
    except Exception as e:
        st.error(f"Error en parse_text_with_pages: {str(e)}")
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
                    file_name=f"ejercicios_{i}.csv",
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
                    file_name=f"ejercicios_{i}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"excel_{block_id}"
                )
            
        except Exception as e:
            st.error(f"Error al procesar datos tabulares: {str(e)}")
            st.text('\n'.join(block))

def query_chunk(client, chunk: Dict[int, str], prompt: str, chunk_info: str) -> str:
    formatted_messages = []
    content_message = f"""Analizando {chunk_info}.
IMPORTANTE: Para CADA ejercicio que encuentres, usa EXACTAMENTE este formato:
Ejercicio X (Página Y): Descripción completa del ejercicio

Reglas:
1. SIEMPRE incluir el número de página entre paréntesis
2. SOLO incluir ejercicios que cumplan con el estándar solicitado
3. Ser preciso con los números de página y ejercicio
4. Proporcionar una descripción completa
5. Si el ejercicio no tiene descripción, indicarlo como "Sin descripción"

Documento a analizar:
"""
    
    for page, content in sorted(chunk.items()):
        content_message += f"[Página {page}]\n{content}\n\n"
    
    formatted_messages.append({
        "role": "user",
        "content": content_message
    })
    formatted_messages.append({"role": "user", "content": prompt})
    
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=4096,
        messages=formatted_messages,
        system="""Eres un asistente especializado en análisis de ejercicios educativos. REGLAS:

1. Para CADA ejercicio encontrado, usa EXACTAMENTE este formato:
   Ejercicio X (Página Y): Descripción detallada
2. SIEMPRE incluye el número de página entre paréntesis
3. La descripción debe incluir todos los detalles relevantes
4. Si no hay descripción disponible, indica "Sin descripción"
5. Analiza SOLO ejercicios que cumplan con el estándar solicitado
6. Sé preciso con los números de página y ejercicio
7. No omitas ningún ejercicio que cumpla con los criterios
8. Verifica dos veces el número de página antes de incluirlo"""
    )
    
    return response.content[0].text
def main():
    st.set_page_config(
        page_title="Análisis de Ejercicios",
        page_icon="📚",
        layout="wide"
    )

    # Inicialización del estado de la sesión
    if "file_chunks" not in st.session_state:
        st.session_state.file_chunks = []
    if "pages_content" not in st.session_state:
        st.session_state.pages_content = {}
    if "last_file" not in st.session_state:
        st.session_state.last_file = None
    if "combined_response" not in st.session_state:
        st.session_state.combined_response = ""
    if "current_exercises" not in st.session_state:
        st.session_state.current_exercises = []
    if "current_df" not in st.session_state:
        st.session_state.current_df = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "analysis_complete" not in st.session_state:
        st.session_state.analysis_complete = False
    if "current_search" not in st.session_state:
        st.session_state.current_search = None
    if "last_analysis" not in st.session_state:
        st.session_state.last_analysis = None
    if "last_combined_response" not in st.session_state:
        st.session_state.last_combined_response = ""

    st.sidebar.title("⚙️ Configuración")
    api_key = st.sidebar.text_input("API Key de Anthropic", type="password")

    st.sidebar.markdown("### 📄 Cargar Archivo")
    uploaded_file = st.sidebar.file_uploader("Sube un archivo PDF o TXT", type=['pdf', 'txt'])

    st.sidebar.markdown("### 🗑️ Gestión")
    if st.sidebar.button("Limpiar Todo", type="primary", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    st.title("📚 Análisis de Ejercicios por Estándar")
    st.markdown("""
    Esta aplicación analiza ejercicios educativos y los clasifica según estándares específicos.
    1. Sube un archivo TXT o PDF
    2. Describe el estándar educativo que quieres buscar
    3. Obtén un análisis detallado y exportable
    """)

    if not api_key:
        st.warning("👈 Introduce tu API Key en la barra lateral para comenzar.")
        return

    try:
        client = anthropic.Client(api_key=api_key)
        
        if uploaded_file:
            st.write("Archivo detectado")  # Debug
            try:
                content = uploaded_file.getvalue().decode('utf-8')
                st.write(f"Contenido leído: {len(content)} bytes")  # Debug
                
                # Verificar si necesitamos reprocesar el archivo
                need_processing = (
                    st.session_state.last_file != uploaded_file.name
                    or not st.session_state.file_chunks
                )
                
                if need_processing:
                    with st.spinner("Procesando archivo..."):
                        st.write("Iniciando procesamiento...")  # Debug
                        pages = parse_text_with_pages(content)
                        if pages:
                            st.write(f"Páginas procesadas: {len(pages)}")  # Debug
                            st.session_state.pages_content = pages
                            st.session_state.file_chunks = chunk_pages_into_files(pages)
                            st.write(f"Chunks creados: {len(st.session_state.file_chunks)}")  # Debug
                            st.session_state.last_file = uploaded_file.name
                            st.sidebar.success(f"Archivo cargado: {uploaded_file.name}")
                else:
                    st.write(f"Usando chunks existentes: {len(st.session_state.file_chunks)}")  # Debug

            except Exception as e:
                st.error(f"Error al procesar el archivo: {str(e)}")
                st.write(f"Traza del error: {traceback.format_exc()}")  # Debug

        # Mostrar último análisis si existe
        if st.session_state.last_analysis:
            st.write("### Último Análisis")
            st.dataframe(st.session_state.last_analysis['dataframe'])
            
            # Generar claves únicas para los botones de descarga
            csv_key = f"last_csv_{uuid.uuid4()}"
            excel_key = f"last_excel_{uuid.uuid4()}"
            
            col1, col2 = st.columns(2)
            with col1:
                csv_data = st.session_state.last_analysis['dataframe'].to_csv(index=False)
                st.download_button(
                    label="📥 Descargar CSV",
                    data=csv_data,
                    file_name="analisis_ejercicios.csv",
                    mime="text/csv",
                    key=csv_key
                )
            with col2:
                excel_buffer = io.BytesIO()
                st.session_state.last_analysis['dataframe'].to_excel(excel_buffer, index=False)
                excel_buffer.seek(0)
                st.download_button(
                    label="📥 Descargar Excel",
                    data=excel_buffer,
                    file_name="analisis_ejercicios.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=excel_key
                )
            
            if st.session_state.last_combined_response:
                st.write("### Resultados Detallados")
                st.write(st.session_state.last_combined_response)

        # Input para el estándar
        if prompt := st.chat_input("Describe el estándar educativo a buscar..."):
            st.session_state.current_search = prompt
            st.session_state.messages.append(ChatMessage("user", prompt))
            with st.chat_message("user"):
                st.write(prompt)

            with st.chat_message("assistant"):
                try:
                    st.write(f"Estado de los chunks: {len(st.session_state.file_chunks)}")  # Debug
                    if st.session_state.file_chunks:
                        st.write("Iniciando análisis de ejercicios")  # Debug
                        combined_response = ""
                        all_exercises = []
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        for i, chunk in enumerate(st.session_state.file_chunks):
                            chunk_start = min(chunk.keys())
                            chunk_end = max(chunk.keys())
                            chunk_info = f"páginas {chunk_start} a {chunk_end}"
                            
                            status_text.text(f"Analizando {chunk_info}...")
                            
                            if i > 0:
                                status_text.text("Esperando para continuar el análisis...")
                                time.sleep(65)
                            
                            response = query_chunk(client, chunk, prompt, chunk_info)
                            if response.strip():
                                chunk_exercises = parse_exercises_from_response(response)
                                if chunk_exercises:
                                    combined_response += f"\n\nResultados de {chunk_info}:\n{response}"
                                    all_exercises.extend(chunk_exercises)
                            
                            progress = (i + 1) / len(st.session_state.file_chunks)
                            progress_bar.progress(progress)
                        
                        status_text.text("Análisis completado!")
                        
                        # Guardar y mostrar resultados
                        if all_exercises:
                            st.write("### Resultados del Análisis")
                            
                            # Ordenar ejercicios por página y número
                            df = pd.DataFrame([{
                                'Ejercicio': ex.number,
                                'Página': ex.page,
                                'Descripción': ex.description,
                                'Estándar': prompt
                            } for ex in all_exercises])
                            
                            df['Ejercicio'] = pd.to_numeric(df['Ejercicio'], errors='coerce')
                            df = df.sort_values(['Página', 'Ejercicio'])
                            
                            # Guardar el análisis actual
                            st.session_state.last_analysis = {
                                'exercises': all_exercises,
                                'dataframe': df,
                                'prompt': prompt
                            }
                            
                            # Guardar la respuesta combinada
                            st.session_state.last_combined_response = combined_response
                            
                            st.dataframe(df)
                            
                            # Generar claves únicas para los botones de descarga
                            current_csv_key = f"current_csv_{uuid.uuid4()}"
                            current_excel_key = f"current_excel_{uuid.uuid4()}"
                            
                            # Botones de descarga
                            col1, col2 = st.columns(2)
                            with col1:
                                csv_data = df.to_csv(index=False)
                                st.download_button(
                                    label="📥 Descargar CSV",
                                    data=csv_data,
                                    file_name="analisis_ejercicios.csv",
                                    mime="text/csv",
                                    key=current_csv_key
                                )
                            with col2:
                                excel_buffer = io.BytesIO()
                                df.to_excel(excel_buffer, index=False)
                                excel_buffer.seek(0)
                                st.download_button(
                                    label="📥 Descargar Excel",
                                    data=excel_buffer,
                                    file_name="analisis_ejercicios.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key=current_excel_key
                                )
                            
                            st.write("### Resultados Detallados")
                            st.write(combined_response)
                        
                        st.session_state.messages.append(ChatMessage("assistant", combined_response))
                    else:
                        st.write("No hay contenido para analizar")
                        st.write("Por favor, asegúrate de que el archivo está cargado correctamente.")

                except Exception as e:
                    st.error(f"Error en el análisis: {str(e)}")
                    st.write(f"Detalles del error: {traceback.format_exc()}")  # Debug

    except Exception as e:
        st.error(f"Error de inicialización: {str(e)}")
        st.write(f"Detalles del error de inicialización: {traceback.format_exc()}")  # Debug

if __name__ == "__main__":
    main()
