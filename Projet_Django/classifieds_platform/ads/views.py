from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from .models import Ad, Category, AdImage, Message,models,User,Profile,Report,Question
from .forms import AdForm, MessageForm,SearchForm,ReportForm, ProfileForm, QuestionForm
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required, user_passes_test

def home(request):
    form = SearchForm(request.GET or None)
    ads = Ad.objects.select_related('category').prefetch_related('adimage_set')
    
    if request.GET and form.is_valid():
        query = form.cleaned_data.get('query')
        category = form.cleaned_data.get('category')
        min_price = form.cleaned_data.get('min_price')
        max_price = form.cleaned_data.get('max_price')
        location = form.cleaned_data.get('location')
        sort_by = form.cleaned_data.get('sort_by')

        if query:
            ads = ads.filter(Q(title__icontains=query) | Q(description__icontains=query))
        if category:
            ads = ads.filter(category=category)
        if min_price is not None:
            ads = ads.filter(price__gte=min_price)
        if max_price is not None:
            ads = ads.filter(price__lte=max_price)
        if location:
            ads = ads.filter(location__icontains=location)
        if sort_by:
            ads = ads.order_by(sort_by)
        
        if not ads.exists():
            messages.info(request, 'No ads match your search criteria.')

    return render(request, 'home.html', {'ads': ads, 'form': form})

def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=password)
            login(request, user)
            return redirect('home')
    else:
        form = UserCreationForm()
    return render(request, 'register.html', {'form': form})

@login_required
def ad_create(request):
    if request.method == 'POST':
        form = AdForm(request.POST)
        if form.is_valid():
            ad = form.save(commit=False)
            ad.user = request.user
            ad.save()
            for image in request.FILES.getlist('images'):
                AdImage.objects.create(image=image, ad=ad)
            return redirect('home')
    else:
        form = AdForm()
    return render(request, 'ad_create.html', {'form': form})

def ad_detail(request, ad_id):
    ad = get_object_or_404(Ad, id=ad_id)
    
    # Récupérer les questions (parent=None) et leurs réponses
    questions = ad.questions.filter(parent__isnull=True).prefetch_related('replies')
    
    question_form = None
    answer_form = None
    
    if request.user.is_authenticated:
        # Formulaire pour poser une question
        if request.method == 'POST' and 'submit_question' in request.POST:
            question_form = QuestionForm(request.POST)
            if question_form.is_valid():
                question = question_form.save(commit=False)
                question.ad = ad
                question.user = request.user
                question.is_answer = False
                question.save()
                messages.success(request, "Votre question a été publiée.")
                return redirect('ad_detail', ad_id=ad_id)
        else:
            question_form = QuestionForm()
        
        # Formulaire pour répondre (si propriétaire ou admin)
        if request.user == ad.user or request.user.is_staff:
            if request.method == 'POST' and 'submit_answer' in request.POST:
                answer_form = QuestionForm(request.POST)
                parent_id = request.POST.get('parent_id')
                if answer_form.is_valid() and parent_id:
                    answer = answer_form.save(commit=False)
                    answer.ad = ad
                    answer.user = request.user
                    answer.is_answer = True
                    answer.parent = get_object_or_404(Question, id=parent_id, ad=ad)
                    answer.save()
                    messages.success(request, "Votre réponse a été publiée.")
                    return redirect('ad_detail', ad_id=ad_id)
            else:
                answer_form = QuestionForm()
    
    return render(request, 'ad_detail.html', {
        'ad': ad,
        'questions': questions,
        'question_form': question_form,
        'answer_form': answer_form,
    })

@login_required
def inbox(request):
    # Get all messages involving the user
    messages_qs = Message.objects.filter(
        Q(sender=request.user) | Q(recipient=request.user)
    ).select_related('sender', 'recipient', 'ad').order_by('-created_at')
    
    # Group conversations by the other user
    conversations = []
    seen_users = set()
    
    for msg in messages_qs:
        other_user = msg.sender if msg.sender != request.user else msg.recipient
        if other_user.id not in seen_users:
            last_message = Message.objects.filter(
                Q(sender=request.user, recipient=other_user) |
                Q(sender=other_user, recipient=request.user)
            ).order_by('-created_at').first()
            
            unread_count = Message.objects.filter(
                sender=other_user,
                recipient=request.user,
                is_read=False
            ).count()
            
            # Get the ad for the last message, if any
            ad = last_message.ad if last_message.ad else None
            
            conversations.append({
                'user': other_user,
                'ad': ad,
                'last_message': last_message,
                'unread_count': unread_count
            })
            seen_users.add(other_user.id)
    
    # Sort by last message timestamp
    conversations.sort(key=lambda x: x['last_message'].created_at, reverse=True)
    
    return render(request, 'inbox.html', {'conversations': conversations})
@login_required
def conversation(request, user_id, ad_id=None):
    other_user = get_object_or_404(User, id=user_id)
    ad = get_object_or_404(Ad, id=ad_id) if ad_id else None
    
    # Mark messages as read
    Message.objects.filter(
        sender=other_user,
        recipient=request.user,
        is_read=False
    ).update(is_read=True)
    
    # Fetch messages between users
    message_list = Message.objects.filter(
        Q(sender=request.user, recipient=other_user) |
        Q(sender=other_user, recipient=request.user)
    ).select_related('sender', 'recipient', 'ad').order_by('created_at')
    
    if request.method == 'POST':
        form = MessageForm(request.POST)
        if form.is_valid():
            message = form.save(commit=False)
            message.sender = request.user
            message.recipient = other_user
            message.ad = ad
            message.save()
            messages.success(request, 'Message sent!')
            return redirect('conversation', user_id=user_id)
    else:
        form = MessageForm()
    
    return render(request, 'conversation.html', {
        'messages': message_list,
        'form': form,
        'other_user': other_user,
        'ad': ad
    })

@login_required
def profile(request):
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        profile = Profile.objects.create(user=request.user)
    
    ads = Ad.objects.filter(user=request.user).select_related('category').prefetch_related('adimage_set')
    
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile has been updated.")
            return redirect('profile')
    else:
        form = ProfileForm(instance=profile)
    
    return render(request, 'profile.html', {'user': request.user, 'profile': profile, 'ads': ads, 'form': form})

@login_required
def report_ad(request, ad_id):
    ad = get_object_or_404(Ad, id=ad_id)
    
    if ad.user == request.user:
        messages.error(request, "You cannot report your own ad.")
        return redirect('ad_detail', ad_id=ad.id)
    
    if request.method == 'POST':
        form = ReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.ad = ad
            report.user = request.user
            report.save()
            messages.success(request, "Your report has been submitted.")
            return redirect('ad_detail', ad_id=ad.id)
    else:
        form = ReportForm()
    
    return render(request, 'report_ad.html', {'form': form, 'ad': ad})

def is_staff(user):
    return user.is_staff or user.is_superuser

@user_passes_test(is_staff)
def report_management(request):
    reports = Report.objects.select_related('ad', 'user').order_by('-created_at')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        report_id = request.POST.get('report_id')
        report = get_object_or_404(Report, id=report_id)
        
        if action == 'resolve':
            report.status = 'resolved'
            report.save()
            messages.success(request, f"Report on '{report.ad.title}' marked as resolved.")
        elif action == 'delete_ad':
            ad = report.ad
            ad_title = ad.title
            ad.delete()  # Cascades to related Report, AdImage, Message
            messages.success(request, f"Ad '{ad_title}' deleted and associated report resolved.")
        
        return redirect('report_management')
    
    return render(request, 'report_management.html', {'reports': reports})

@login_required
def ad_edit(request, ad_id):
    ad = get_object_or_404(Ad, id=ad_id)
    if ad.user != request.user:
        messages.error(request, "Vous n'êtes pas autorisé à modifier cette annonce.")
        return redirect('profile')
    
    if request.method == 'POST':
        form = AdForm(request.POST, request.FILES, instance=ad)
        if form.is_valid():
            ad = form.save(commit=False)
            ad.status = 'pending'  # Nouvelle modération
            ad.save()
            form.save_m2m()  # Sauvegarde des relations (par exemple, images)
            messages.success(request, f"L'annonce '{ad.title}' a été modifiée et est en attente de modération.")
            return redirect('profile')
    else:
        form = AdForm(instance=ad)
    
    return render(request, 'ad_edit.html', {'form': form, 'ad': ad})

@login_required
def ad_delete(request, ad_id):
    ad = get_object_or_404(Ad, id=ad_id)
    if ad.user != request.user:
        messages.error(request, "Vous n'êtes pas autorisé à supprimer cette annonce.")
        return redirect('profile')
    
    if request.method == 'POST':
        ad_title = ad.title
        ad.delete()  # Cascade vers AdImage, Report, Message
        messages.success(request, f"L'annonce '{ad_title}' a été supprimée.")
        return redirect('profile')
    
    return redirect('profile')  # GET redirige vers profile

