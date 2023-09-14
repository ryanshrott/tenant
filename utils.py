import streamlit as st
import boto3
from io import BytesIO
import os
from docx import Document
from io import BytesIO
from pytesseract import pytesseract
from pytesseract import image_to_string
from PIL import Image as PILImage
from pdf2image import convert_from_bytes
from dotenv import load_dotenv
from pymongo import MongoClient
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import PyPDF2
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import docx2pdf
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.units import inch
from utils import *

load_dotenv()
# AWS Credentials from OS environment variables
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
BUCKET_NAME = os.environ.get('BUCKET_NAME')
LISTINGS_FOLDER = "listings/"
MONGO_URI = os.environ.get('MONGO_URI')

# Initialize S3 client
@st.cache_resource
def s3_client():
    s3 = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
    return s3
s3 = s3_client()


@st.cache_resource
def mongo_collection():
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client['smartbids']  
    return db['tenants']

# Initialize MongoDB client
tenants_collection = mongo_collection()

def save_to_mongo(tenant_name, email_address, phone_number, about_you, credit_score, job_summary, landlord_phone, youtube_intro, paystub_summary, selected_address):
    """Save or update tenant data in MongoDB"""
    data = {
        "tenant_name": tenant_name,
        "email_address": email_address,
        "phone_number": phone_number,
        "about_you": about_you,
        "credit_score": credit_score,
        "job_summary": job_summary,
        "landlord_phone": landlord_phone,
        "youtube_intro": youtube_intro,
        "paystub_summary": paystub_summary
    }
    
    # Filter out fields with None or empty string values
    data = {k: v for k, v in data.items() if v is not None and v != ""}
    
    # Update the tenant's data and append the new address to the 'units' list
    tenants_collection.update_one(
        {"email_address": email_address},
        {
            "$set": data,
            "$addToSet": {"units": selected_address}  # $addToSet adds the address to the list only if it doesn't already exist
        },
        upsert=True
    )

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
        image = PILImage.open(BytesIO(image_bytes))
        raw_text = str(image_to_string(image))
        print(raw_text)
        image_content.append(raw_text)
    
    return "\n".join(image_content)

def process_and_upload_file(file, doc_type, tenant_name, selected_address, only_write_base_file=False):
    print(file, doc_type, tenant_name, selected_address)
    # Check if the file is a string (like youtube_intro) or a file-like object
    if isinstance(file, str):
        print('string')
        # If it's a string, upload it directly
        upload_to_s3(file, doc_type, tenant_name, selected_address, is_text=True)
        return

    # If it's a file-like object, determine the file type from the file extension
    file_type = file.name.split('.')[-1].lower()
    print(file_type)

    # Save the original file
    upload_to_s3(file, doc_type, tenant_name, selected_address)
    if not only_write_base_file:
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
