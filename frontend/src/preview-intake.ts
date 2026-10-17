import type { IntakePages } from './Onboarding';
const pages: IntakePages = [
  {
    "title": "What do you want to build?",
    "questions": [
      {
        "id": "idea",
        "label": "Software idea",
        "placeholder": "The problem and the app, website or software enhancement that could solve it.",
        "multiline": true
      }
    ]
  },
  {
    "title": "Who is it for?",
    "questions": [
      {
        "id": "customer",
        "label": "Your first customers",
        "placeholder": "For example, independent dental clinics",
        "multiline": false
      },
      {
        "id": "location",
        "label": "Where will you start?",
        "placeholder": "City, country or online market",
        "multiline": false
      }
    ]
  },
  {
    "title": "What are you working with?",
    "questions": [
      {
        "id": "budget",
        "label": "Starting budget",
        "placeholder": "Amount and currency, or no budget yet",
        "multiline": false
      },
      {
        "id": "founderSkills",
        "label": "Your skills and resources",
        "placeholder": "What can you deliver yourself, and where do you need help?",
        "multiline": true
      },
      {
        "id": "goal",
        "label": "Your first milestone",
        "placeholder": "What would progress look like in 30 days?",
        "multiline": true
      }
    ]
  }
];
export default pages;
