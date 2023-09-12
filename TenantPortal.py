import streamlit as st
import boto3
from io import BytesIO
import os
from docx import Document
from io import BytesIO
from pytesseract import pytesseract
from pytesseract import image_to_string
from PIL import Image
from pdf2image import convert_from_bytes
from dotenv import load_dotenv
load_dotenv()
# AWS Credentials from OS environment variables
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
BUCKET_NAME = os.environ.get('BUCKET_NAME')
LISTINGS_FOLDER = "listings/"

# Initialize S3 client
s3 = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY)

# only do this if you are on windows operating system
if os.name == 'nt':
    # Add the poppler path to the PATH environment variable
    poppler_path = r"C:\Program Files\poppler-23.08.0\Library\bin"
    os.environ["PATH"] += os.pathsep + poppler_path
    # Set the path for tesseract
    pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  # Change this to the path where tesseract is installed

def extract_text_from_docx(file):
    doc = Document(file)
    full_text = []
    for paragraph in doc.paragraphs:
        full_text.append(paragraph.text)
    return '\n'.join(full_text)


def convert_pdf_to_images(file_bytes, dpi=300):
    images = convert_from_bytes(file_bytes.getvalue(), dpi=dpi)
    final_images = []

    for index, image in enumerate(images):
        image_byte_array = BytesIO()
        image.save(image_byte_array, format='jpeg', optimize=True)
        image_byte_array = image_byte_array.getvalue()
        final_images.append(dict({index: image_byte_array}))

    return final_images

def extract_text_with_pytesseract(list_dict_final_images):
    image_list = [list(data.values())[0] for data in list_dict_final_images]
    image_content = []
    
    for index, image_bytes in enumerate(image_list):
        image = Image.open(BytesIO(image_bytes))
        raw_text = str(image_to_string(image))
        st.write(raw_text)
        image_content.append(raw_text)
    
    return "\n".join(image_content)

def process_and_upload_file(file, doc_type, tenant_name, selected_address):
    # Check if the file is a string (like youtube_intro) or a file-like object
    if isinstance(file, str):
        # If it's a string, upload it directly
        upload_to_s3(file, doc_type, tenant_name, selected_address, is_text=True)
        return

    # If it's a file-like object, determine the file type from the file extension
    file_type = file.name.split('.')[-1].lower()

    # Save the original file
    upload_to_s3(file, doc_type, tenant_name, selected_address)

    # If the file type is PDF, convert to images and extract text
    if file_type == 'pdf':
        images = convert_pdf_to_images(file)
        for idx, image_data in enumerate(images):
            image_key = f"{LISTINGS_FOLDER}{selected_address}/{tenant_name.replace(' ', '_')}/{doc_type.replace(' ', '_')}/{file.name}_page_{idx + 1}.jpeg"
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key=image_key,
                Body=image_data[list(image_data.keys())[0]],
                Metadata={
                    'tenant_name': tenant_name,
                    'address': selected_address,
                    'document_type': doc_type
                }
            )
        text_content = extract_text_with_pytesseract(images)
        
        # Use the original file name but change the extension to .txt
        text_file_name = file.name.rsplit('.', 1)[0] + '.txt'
        text_key = f"{LISTINGS_FOLDER}{selected_address}/{tenant_name.replace(' ', '_')}/{doc_type.replace(' ', '_')}/{text_file_name}"
        
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=text_key,
            Body=text_content,
            Metadata={
                'tenant_name': tenant_name,
                'address': selected_address,
                'document_type': doc_type
            }
        )
    elif file_type in ['doc', 'docx']:
        text_content = extract_text_from_docx(file)
        
        # Use the original file name but change the extension to .txt
        text_file_name = file.name.rsplit('.', 1)[0] + '.txt'
        text_key = f"{LISTINGS_FOLDER}{selected_address}/{tenant_name.replace(' ', '_')}/{doc_type.replace(' ', '_')}/{text_file_name}"
        
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=text_key,
            Body=text_content,
            Metadata={
                'tenant_name': tenant_name,
                'address': selected_address,
                'document_type': doc_type
            }
        )


def fetch_listings():
    """Fetch available listings from S3"""
    response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=LISTINGS_FOLDER, Delimiter='/')
    if 'CommonPrefixes' not in response:
        return []
    return [prefix['Prefix'].replace(LISTINGS_FOLDER, '').rstrip('/') for prefix in response['CommonPrefixes']]
def upload_to_s3(content, doc_type, tenant_name, address, is_text=False):
    """Upload a file or text to an S3 bucket with structured naming and metadata"""
    buffer = BytesIO()
    
    if is_text:
        # If the content is a string, encode it
        buffer.write(content.encode())
    else:
        # If the content is a file-like object, read its chunks
        for chunk in content:
            buffer.write(chunk)
    
    buffer.seek(0)
    
    # Structured naming convention: listings/address/candidate_name/documentType/document_filename.ext
    if is_text:
        key = f"{LISTINGS_FOLDER}{address}/{tenant_name.replace(' ', '_')}/{doc_type.replace(' ', '_')}/file.txt"
    else:
        key = f"{LISTINGS_FOLDER}{address}/{tenant_name.replace(' ', '_')}/{doc_type.replace(' ', '_')}/{content.name}"
    
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=buffer,
        Metadata={
            'tenant_name': tenant_name,
            'address': address,
            'document_type': doc_type
        }
    )


def main():
    st.title("Document Upload for Tenants")

    with st.form(key='upload_form'):
        st.markdown('#### Required Documents')
        tenant_name = st.text_input("Enter your full name:")
        available_listings = fetch_listings()
        if not available_listings:
            st.warning("No listings available at the moment. Please ask your landlord/realtor to create a listing.")
            selected_address = None  # Set to None if no listings available
        else:
            selected_address = st.selectbox("Select the address you're applying for:", available_listings)

        credit_score_files = st.file_uploader("Upload your Credit Score(s)", type=['pdf', 'docx', 'txt'], accept_multiple_files=True)
        job_letter_files = st.file_uploader("Upload your Job Letter(s)", type=['pdf',  'docx', 'txt'], accept_multiple_files=True)
        paystub_files = st.file_uploader("Upload your Paystub(s)", type=['pdf', 'docx', 'txt'], accept_multiple_files=True)
        st.markdown('#### Optional Documents')
        youtube_intro = st.text_input("Enter a 1-minute YouTube video intro URL (optional)")
        cv_file = st.file_uploader("Upload your CV (optional)", type=['pdf', 'docx', 'txt'])
        bank_files = st.file_uploader("Upload Bank Statements (optional)", type=['pdf', 'doc', 'txt'], accept_multiple_files=True)
        submit_button = st.form_submit_button(label='Upload All Documents')

        if submit_button:
            if tenant_name and selected_address:
                if credit_score_files:
                    for file in credit_score_files:
                        process_and_upload_file(file, "Credit Score", tenant_name, selected_address)
                if job_letter_files:
                    for file in job_letter_files:
                        process_and_upload_file(file, "Job Letter", tenant_name, selected_address)
                if paystub_files:
                    for file in paystub_files:
                        process_and_upload_file(file, "Paystub", tenant_name, selected_address)
                if cv_file:
                    process_and_upload_file(cv_file, "CV", tenant_name, selected_address)
                if youtube_intro:
                    process_and_upload_file(youtube_intro, "YouTube URL", tenant_name, selected_address)
                if bank_files:
                    for file in bank_files:
                        process_and_upload_file(file, "Bank Statement", tenant_name, selected_address)
                st.success("Documents and URLs uploaded successfully!")
            else:
                st.warning("Please fill in all required fields.")


if __name__ == "__main__":
    main()
