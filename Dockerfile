# Use a lightweight base image with Conda pre-installed
FROM continuumio/miniconda3

# Set working directory
WORKDIR /app

# Copy environment.yml and install dependencies
COPY environment.yml /app/environment.yml
RUN conda env create -n CDSE -f environment.yml

# Activate the environment and ensure it works
RUN echo "source activate CDSE" > ~/.bashrc
ENV PATH=/opt/conda/envs/CDSE/bin:$PATH
ENV PROJ_LIB=/opt/conda/envs/CDSE/share/proj

# Copy the Python script into the container
COPY search.py .
COPY download.py .

# Copy the entrypoint script into the container
COPY entrypoint.sh .

# Make the entrypoint script executable
RUN chmod +x entrypoint.sh

# Set the entrypoint to the shell script
ENTRYPOINT ["./entrypoint.sh"]

# Default arguments (if any) to pass to the script
CMD []