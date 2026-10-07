export function contactForm() {
    return {
        formData: {
            name: '',
            email: '',
            phone: '',
            message: ''
        },
        submitted: false,
        submitForm() {
            console.log('Form submitted:', this.formData);
            this.submitted = true;

            // Reset form after 3 seconds
            setTimeout(() => {
                this.formData = {
                    name: '',
                    email: '',
                    phone: '',
                    message: ''
                };
                this.submitted = false;
            }, 3000);
        }
    };
}
