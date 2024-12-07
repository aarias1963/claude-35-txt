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

def chunk_pages_into_files(pages_content: Dict[int, str], pages_per_chunk: int = 25) -> List[Dict[int, str]]:
    st.write("Iniciando procesamiento...")  # Debug
    pages_list = sorted(pages_content.items())
    chunks = []
    
    for i in range(0, len(pages_list), pages_per_chunk):
        chunk = dict(pages_list[i:i + pages_per_chunk])
        chunks.append(chunk)
    
    return chunks

def parse_text_with_pages(text):
    pages = {}
    current_page = None
    current_content = []
    
    lines = text.split('\n')
    
    try:
        page_pattern = r'\[Página (\d+)\]'
        
        for i, line in enumerate(lines):
            match = re.match(page_pattern, line, re.UNICODE)
            if match:
                if current_page:
                    pages[current_page] = '\n'.join(current_content)
                current_page = int(match.group(1))
                current_content = []
            elif current_page is not None:
                current_content.append(line)
        
        if current_page and current_content:
            pages[current_page] = '\n'.join(current_content)
        
        return pages
    except Exception as e:
        st.error(f"Error procesando el texto: {str(e)}")
        raise e

def parse_exercises_from_response(response: str) -> List[Exercise]:
    exercises = []
    exercise_pattern = r'Ejercicio\s+(\d+)\s*\(Página\s+(\d+)\)\s*:?\s*((?:(?!Ejercicio\s+\d+\s*\(Página).|[\n])*)'
    
    matches = re.finditer(exercise_pattern, response, re.DOTALL | re.IGNORECASE)
    
    for match in matches:
        number = match.group(1)
        page = int(match.group(2))
        description = match.group(3).strip() if match.group(3) else "Sin descripción"
        exercises.append(Exercise(number, page, description, ""))
            
    return exercises

def query_chunk(client, chunk: Dict[int, str], prompt: str, chunk_info: str) -> str:
    formatted_messages = []
    content_message = f"""Analizando {chunk_info}.
IMPORTANTE: Para CADA ejercicio que encuentres, usa EXACTAMENTE este formato:
Ejercicio X (Página Y): Descripción completa del ejercicio

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
3. La descripción debe ser clara y completa
4. Si no hay descripción, indica "Sin descripción"
5. Analiza SOLO ejercicios que cumplan con el estándar solicitado"""
    )
    
    return response.content[0].text
def main():
    st.set_page_config(
        page_title="Análisis de Ejercicios",
        page_icon="📚",
        layout="wide"
    )

    # Inicialización mínima del estado
    if "file_chunks" not in st.session_state:
        st.session_state.file_chunks = []

    st.sidebar.title("⚙️ Configuración")
    api_key = st.sidebar.text_input("API Key de Anthropic", type="password")

    st.sidebar.markdown("### 📄 Cargar Archivo")
    uploaded_file = st.sidebar.file_uploader("Sube un archivo PDF o TXT", type=['pdf', 'txt'])

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
            try:
                # Procesar archivo
                content = uploaded_file.getvalue().decode('utf-8')
                pages = parse_text_with_pages(content)
                if pages:
                    st.session_state.file_chunks = chunk_pages_into_files(pages)
                    st.success(f"Archivo cargado: {uploaded_file.name}")

            except Exception as e:
                st.error(f"Error al procesar el archivo: {str(e)}")

        # Input para el estándar
        if prompt := st.chat_input("Describe el estándar educativo a buscar..."):
            try:
                if st.session_state.file_chunks:
                    # Iniciar análisis
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
                    
                    # Mostrar resultados
                    if all_exercises:
                        st.write("### Resultados del Análisis")
                        
                        df = pd.DataFrame([{
                            'Ejercicio': ex.number,
                            'Página': ex.page,
                            'Descripción': ex.description,
                            'Estándar': prompt
                        } for ex in all_exercises])
                        
                        df['Ejercicio'] = pd.to_numeric(df['Ejercicio'], errors='coerce')
                        df = df.sort_values(['Página', 'Ejercicio'])
                        
                        st.dataframe(df)
                        
                        # Botones de descarga
                        col1, col2 = st.columns(2)
                        with col1:
                            csv_data = df.to_csv(index=False)
                            st.download_button(
                                label="📥 Descargar CSV",
                                data=csv_data,
                                file_name="analisis_ejercicios.csv",
                                mime="text/csv"
                            )
                        with col2:
                            excel_buffer = io.BytesIO()
                            df.to_excel(excel_buffer, index=False)
                            excel_buffer.seek(0)
                            st.download_button(
                                label="📥 Descargar Excel",
                                data=excel_buffer,
                                file_name="analisis_ejercicios.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )
                        
                        st.write("### Resultados Detallados")
                        st.write(combined_response)
                    else:
                        st.write("No se encontraron ejercicios que cumplan con el estándar especificado.")
                else:
                    st.warning("Por favor, carga un archivo antes de realizar el análisis.")

            except Exception as e:
                st.error(f"Error en el análisis: {str(e)}")

    except Exception as e:
        st.error(f"Error de inicialización: {str(e)}")

if __name__ == "__main__":
    main()
