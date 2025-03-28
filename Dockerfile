# ���������� ����� Python 3.11 � �������� ��������
FROM python:3.11-slim-buster

# ������������� ���������� ���������
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# ������� ������� ����������
WORKDIR /app

# �������� requirements.txt � ������������� �����������
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# �������� ��� ����� ������� � ������� ����������
COPY . .

# ������������� ����� �� ���������� ��� ������� �������
RUN chmod +x run.sh

# ��������� ����
CMD ["./run.sh"]
